import re
from concurrent.futures import Future

import rclpy
from rclpy.qos import QoSProfile, DurabilityPolicy, HistoryPolicy

from foros_msgs.msg import RaftState
from foros_msgs.srv import InitRaft

from worms_cortex.manager_node import ManagerNode


class BrainNode(ManagerNode):
    """
    Primary brain of the WORMS system. A single node capable of coordinating with
    other brains and launching child nodes when needed.
    """

    # Regex to capture the node ID from the InitRaft service
    _INIT_SVC_RE = re.compile(r".+/init_node_(\d+)$")

    # Lookup dictionary for mapping RaftState enum to a string
    _RAFT_STATE_NAMES = {
        value: name
        for name, value in vars(RaftState).items()
        if name.isupper() and isinstance(value, int)
    }

    def __init__(self):
        """Initializes a WORMS Brain."""
        super().__init__("brain")

        # Parameters
        self.declare_parameter("cluster_name", "")
        self.declare_parameter("node_id", -1)
        self.declare_parameter("discovery_timeout_ms", 3000)

        self._cluster_name = self.get_parameter("cluster_name").value
        self._node_id = int(self.get_parameter("node_id").value)  # type: ignore
        self._discovery_sec = self.get_parameter("discovery_timeout_ms").value / 1000.0  # type: ignore

        if not self._cluster_name:
            raise RuntimeError("cluster_name is required")
        if self._node_id < 0:
            raise RuntimeError("node_id is required")

        self._membership_svc_name = f"/{self._cluster_name}/request_membership"
        self._raft_state = RaftState.STANDBY
        self._peer_ids: list[int] = []

        # Our current raft state
        self.create_subscription(
            RaftState,
            "raft_interface/state",
            self._on_raft_state,
            QoSProfile(
                depth=1,
                durability=DurabilityPolicy.TRANSIENT_LOCAL,
                history=HistoryPolicy.KEEP_LAST,
            ),
        )

        # Client for requesting raft to begin
        self._init_client = self.create_client(
            InitRaft,
            f"raft_interface/init_node_{self._node_id}",
        )

        # Delayed discovery to let nodes launch
        self._discovery_timer = self.create_timer(
            self._discovery_sec,
            self._on_discovery_timer,
        )

    def _on_raft_state(self, msg: RaftState) -> None:
        prev, self._raft_state = self._raft_state, msg.state

        # State didnt change
        if prev == self._raft_state:
            return

        # Debug to track state changes
        self.get_logger().debug(
            f"State change: {self._RAFT_STATE_NAMES[prev]} -> {self._RAFT_STATE_NAMES[self._raft_state]}"
        )

        # TODO: Insert raft state machine callbacks here (on_leader)

    def _on_discovery_timer(self) -> None:
        self._discovery_timer.cancel()

        # Existing cluster
        if self._server_exists(self._membership_svc_name):
            self.get_logger().info("Existing cluster found. Joining as learner...")
            self._call_init_raft([])
            return

        peer_ids = self._find_peer_ids()

        # Retry discovery
        if not peer_ids:
            self.get_logger().warn("No peers found. Retrying discovery...")
            self._peer_ids = []
            self._discovery_timer = self.create_timer(
                self._discovery_sec,
                self._on_discovery_timer,
            )
            return

        # Require node discovery to settle (two sequential discoveries)
        if set(self._peer_ids) != set(peer_ids):
            self._peer_ids = peer_ids
            self._discovery_timer = self.create_timer(
                self._discovery_sec,
                self._on_discovery_timer,
            )
            return

        # Form a new cluster
        all_ids = sorted({self._node_id} | set(self._peer_ids))
        self.get_logger().info(f"Forming new cluster with members: {all_ids}")
        self._call_init_raft(all_ids)

    def _call_init_raft(self, member_ids: list[int]) -> None:
        if not self._init_client.wait_for_service(timeout_sec=5.0):
            self.get_logger().error("InitRaft service not available.")
            return

        req = InitRaft.Request()
        req.member_ids = [int(i) for i in member_ids]

        # Send the call async so we know if it was successful
        future = self._init_client.call_async(req)
        future.add_done_callback(lambda f: self._on_init_done(f))

    def _on_init_done(self, future: Future) -> None:
        result: InitRaft.Response = future.result()
        if result is None or not result.success:
            self.get_logger().error("InitRaft request failed.")

    def _find_peer_ids(self) -> list[int]:
        peers = []
        for svc_name, _ in self.get_service_names_and_types():
            match = self._INIT_SVC_RE.match(svc_name)

            # Append peer if matched
            if match:
                peer_id = int(match.group(1))
                if peer_id != self._node_id:
                    peers.append(peer_id)

        return peers

    def _server_exists(self, sv_name: str) -> bool:
        # NOTE: This checks just servers, excluding clients
        return any(
            server_name == sv_name
            for node_name, node_namespace in self.get_node_names_and_namespaces()
            for server_name, _ in self.get_service_names_and_types_by_node(
                node_name, node_namespace
            )
        )


def main(args=None):
    rclpy.init(args=args)
    node = BrainNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
