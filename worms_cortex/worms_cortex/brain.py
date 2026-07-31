import re
from pathlib import Path
from concurrent.futures import Future

import rclpy
from rclpy.publisher import Publisher
from rclpy.qos import QoSProfile, DurabilityPolicy, HistoryPolicy
from launch_ros.actions import Node as NodeAction
from ament_index_python.packages import get_package_share_directory

from foros_msgs.msg import RaftState
from foros_msgs.srv import InitRaft

from worms_manager.manager_node import ManagerNode
from worms_manager.srv import LaunchNode
from worms_manager_msgs.msg import MissionCommand, SubroutineCommand

from worms_arthron_msgs.msg import NamedConfiguration

_TRANSIENT_LOCAL_QOS = QoSProfile(
    depth=1,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
)


class Brain(ManagerNode):
    """
    Primary brain of the WORMS system. A single node capable of coordinating with
    other brains and launching child nodes when needed.
    """

    # Regex to capture the node ID and name from the InitRaft service
    _INIT_SVC_RE = re.compile(r"^/([^/]+)/.+/init_node_(\d+)$")

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
        self.declare_parameter("cluster_name", rclpy.Parameter.Type.STRING)
        self.declare_parameter("node_id", rclpy.Parameter.Type.INTEGER)
        self.declare_parameter("discovery_timeout_s", 3.0)

        self._cluster_name = (
            self.get_parameter("cluster_name").get_parameter_value().string_value
        )
        self._node_id = (
            self.get_parameter("node_id").get_parameter_value().integer_value
        )
        self._discovery_sec = (
            self.get_parameter("discovery_timeout_s").get_parameter_value().double_value
        )

        # Raft and discovery
        self._membership_svc_name = f"/{self._cluster_name}/request_membership"
        self._namespace = self.get_system_namespace(self.get_namespace())
        self._raft_state = RaftState.STANDBY
        self._leader_id = RaftState.UNKNOWN_LEADER
        self._peer_ids: dict[int, str] = {}  # {id: namespace}

        # Our current raft state
        self.create_subscription(
            RaftState,
            "raft_interface/state",
            self._on_raft_state,
            _TRANSIENT_LOCAL_QOS,
        )

        # Client for requesting raft to begin
        self._init_client = self.create_client(
            InitRaft,
            f"raft_interface/init_node_{self._node_id}",
        )

        # Child communication
        self._child_name_format = self.get_namespace() + "/{}"
        self._cur_subroutine_name = ""
        self._subroutine_command_pub: Publisher | None = None

        # Commands from mission control
        self.create_subscription(
            MissionCommand,
            "/mission_command",
            self._on_mission_command,
            _TRANSIENT_LOCAL_QOS,
        )

        # System topology
        self._cur_configuration: str | None = None

        # Current configuration from topology system
        self._config_sub = self.create_subscription(
            NamedConfiguration,
            "named_configuration",
            self._on_named_configuration,
            _TRANSIENT_LOCAL_QOS,
        )

        # Delayed discovery to let nodes launch
        self._discovery_timer = self.create_timer(
            self._discovery_sec,
            self._on_discovery_timer,
        )

    # region Node name helpers

    @property
    def leader_namespace(self) -> str:
        """Returns the system namespace of the current leader."""
        return (
            self._peer_ids.get(self._leader_id, "")
            if self._leader_id != self._node_id
            else self._namespace
        )

    def get_system_namespace(self, resolved_name: str) -> str:
        """Returns the leading namespace of the passed node."""
        return resolved_name.strip("/").split("/")[0]

    def is_brain_node(self, resolved_name: str) -> bool:
        """Returns True if the passed node is another brain node."""
        return resolved_name.strip("/").split("/")[-1] == "brain"

    def is_current_leader(self, resolved_name: str) -> bool:
        """Returns True if the passed node is currently the leader."""
        return (
            self.is_brain_node(resolved_name)
            and self.get_system_namespace(resolved_name) == self.leader_namespace
        )

    # endregion

    # region Configuration

    def _on_named_configuration(self, msg: NamedConfiguration) -> None:
        """Callback to handle a new named configuration from the topology."""
        self._cur_configuration = msg.config_name if msg.known_config else None

    # endregion

    # region Mission control

    def _on_mission_command(self, msg: MissionCommand) -> None:
        """Callback to handle new command from mission control."""
        # Only the leader can execute commands
        if not self.is_current_leader(self.get_fully_qualified_name()):
            return

        child_name = self._child_name_format.format(msg.node_name)

        # This node hasn't spawned yet
        if (
            child_name != self._cur_subroutine_name
            or self._subroutine_command_pub is None
        ):
            # Kill the current subroutine if one is running
            if self._subroutine_command_pub is not None:
                self.kill_node(self._cur_subroutine_name)

            # Spawn the node
            config = self._get_subroutine_config(msg.package, msg.executable)
            node_action = NodeAction(
                package=msg.package,
                executable=msg.executable,
                name=msg.node_name,
                namespace=self.get_namespace(),
                parameters=[config] if config else None,
            )
            self.spawn_node(node_action)
            self._cur_subroutine_name = child_name

            # Create a new publisher
            self._subroutine_command_pub = self.create_publisher(
                SubroutineCommand,
                f"{child_name}/subroutine_command",
                _TRANSIENT_LOCAL_QOS,
            )

        # Forward the command to the node
        self._subroutine_command_pub.publish(msg.cmd)

    def _get_subroutine_config(self, package: str, executable: str) -> str | None:
        """
        Attempt to get the config yaml for a given subroutine. Searches the package's
        `config` directory expecting to find an `<executable>.yaml` located in either
        the `subroutines` or `<system_configuration>` folders.

        Args:
            package (str): The ros package the subroutine belongs to
            executable (str): The specific executable to search for

        Returns:
            config_path (str | None): The config path if it was found
        """
        config_dir = Path(get_package_share_directory(package)) / "config"

        # Default to subroutines path, take specific config if it exists
        best_path = config_dir / "subroutines" / f"{executable}.yaml"
        if self._cur_configuration:
            file_path = config_dir / self._cur_configuration / f"{executable}.yaml"
            best_path = file_path if file_path.exists() else best_path

        if not best_path.exists():
            self.get_logger().debug(f"Found no config for {executable}")
            return None

        return str(best_path)

    # endregion

    # region Raft management

    def _on_discovery_timer(self) -> None:
        """
        Callback for delayed peer discovery. Starts or joins the raft cluster based
        on peer status.
        """
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
            self._peer_ids = {}
            self._discovery_timer = self.create_timer(
                self._discovery_sec,
                self._on_discovery_timer,
            )
            return

        # Require node discovery to settle (two sequential discoveries)
        if set(self._peer_ids.keys()) != set(peer_ids.keys()):
            self._peer_ids = peer_ids
            self._discovery_timer = self.create_timer(
                self._discovery_sec,
                self._on_discovery_timer,
            )
            return

        # Form a new cluster
        all_ids = sorted({self._node_id} | set(self._peer_ids.keys()))
        self.get_logger().info(f"Forming new cluster with members: {all_ids}")
        self._call_init_raft(all_ids)

    def _find_peer_ids(self) -> dict[int, str]:
        """
        Discover peers within the ROS network.

        Returns:
            peers ({int: str}): Raft node IDs for each peer in the system
        """
        peers = {}
        for svc_name, _ in self.get_service_names_and_types():
            match = self._INIT_SVC_RE.match(svc_name)
            if not match:
                continue

            namespace = match.group(1)
            peer_id = int(match.group(2))

            if peer_id == self._node_id:
                continue

            peers[peer_id] = namespace

        return peers

    def _server_exists(self, sv_name: str) -> bool:
        """
        Checks if a server has been initialized for a given service.

        Args:
            sv_name (str): The full name of the service

        Returns:
            exists (bool): True if the server exists, else False
        """
        # NOTE: This checks just servers, excluding clients
        return any(
            server_name == sv_name
            for node_name, node_namespace in self.get_node_names_and_namespaces()
            for server_name, _ in self.get_service_names_and_types_by_node(
                node_name, node_namespace
            )
        )

    def _call_init_raft(self, member_ids: list[int]) -> None:
        """
        Send the raft initialization service with the passed members.

        Args:
            member_ids ([int]): The node IDs of the cluster to initialize, if empty
                the node will attempt to join the existing cluster.
        """
        if not self._init_client.wait_for_service(timeout_sec=5.0):
            self.get_logger().error("InitRaft service not available.")
            return

        req = InitRaft.Request()
        req.member_ids = [int(i) for i in member_ids]

        # Send the call async so we know if it was successful
        future = self._init_client.call_async(req)
        future.add_done_callback(lambda f: self._on_init_done(f))

    def _on_init_done(self, future: Future) -> None:
        """
        Delayed callback for the raft initialization response.

        Args:
            future (Future): Async future returning the InitRaft response
        """
        result: InitRaft.Response = future.result()
        if result is None or not result.success:
            self.get_logger().error("InitRaft request failed.")

    def _on_raft_state(self, msg: RaftState) -> None:
        """
        Callback function for `raft_interface/state`. Updates the internal state
        and triggers any state callbacks.
        """
        prev_state, self._raft_state = self._raft_state, msg.state
        prev_leader, self._leader_id = self._leader_id, msg.leader_id

        state_changed = prev_state != self._raft_state
        leader_changed = prev_leader != self._leader_id

        # No change between messages
        if not state_changed and not leader_changed:
            return

        # Debug to track changes
        if state_changed:
            self.get_logger().debug(
                f"State change: {self._RAFT_STATE_NAMES[prev_state]} "
                f"-> {self._RAFT_STATE_NAMES[self._raft_state]}"
            )
        if leader_changed:
            self.get_logger().debug(
                f"Leader change: {prev_leader} -> {self._leader_id}"
            )

        # TODO: Insert raft state machine callbacks here (on_leader)

    # endregion

    # region Overloads

    def _launch_node_callback(
        self, request: LaunchNode.Request, response: LaunchNode.Response
    ) -> LaunchNode.Response:
        """Extends parent to respect raft leadership and set up communication."""
        is_leader = self.is_current_leader(self.get_fully_qualified_name())

        if is_leader:
            # Leader only accepts requests from its children
            if self.is_child(request.source):
                return super()._launch_node_callback(request, response)
            else:
                self.get_logger().error(
                    f"Node launch request from {request.source} denied, request to a "
                    "leader must come from child nodes"
                )
                response.success = False
                return response

        else:
            # Non-leaders can accept requests from the current leader
            if self.is_current_leader(request.source):
                return super()._launch_node_callback(request, response)
            else:
                self.get_logger().error(
                    f"Node launch request from {request.source} denied, request to a "
                    f"non-leader must come from the leader ({self.leader_namespace})"
                )
                response.success = False
                return response

    def spawn_node(self, action: NodeAction) -> None:
        """Extends parent to respect raft leadership and set up communication."""
        if self.is_current_leader(self.get_fully_qualified_name()):
            return super().spawn_node(action)

        self.get_logger().error(
            "Spawn node request denied, this node is not the leader"
        )

    # endregion


def main(args=None):
    rclpy.init(args=args)
    node = Brain()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
