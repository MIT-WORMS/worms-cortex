import os
import socket
import threading
from collections import defaultdict

from rclpy.node import Node

from launch import Event
from launch.events.process import ShutdownProcess
from launch_ros.actions import Node as NodeAction
from launch_ros.events.matchers import matches_node_name

from worms_cortex.actions import SOCKET_ENVIRON
from worms_cortex.events import LaunchNode as LaunchNodeEvent
from worms_cortex.events import AckNode
from worms_cortex.events.serialize import EventStream
from worms_cortex.srv import LaunchNode as LaunchNodeSrv


class ManagerNodeMixin:
    """
    Mixin class to add manager functionality to a `Node`.

    This class should not be instantiated on its own, and instead used with multiple
    inheritence along with a `Node`.
    """

    def __init__(self):
        """Initialize a `ManagerNode`."""
        if not isinstance(self, Node):
            raise RuntimeError(
                "`ManagerNodeMixin` uses `Node` fields"
                "so Node needs to be in the inheritance tree."
            )
        self._logger = self.get_logger()
        self._name = self.get_name()

        # Try to retrieve the communications socket
        fd = os.environ.get(SOCKET_ENVIRON, None)
        # TODO (trevor): Reword if we add support for ros2 run
        if fd is None:
            raise RuntimeError(
                "Failed to retrieve launch service file descriptor. ManagerNodes must "
                "be launched using `ros2 launch` with the `ManagerNode` action."
            )
        if not fd.isnumeric():
            raise RuntimeError(
                f"Malformed file descriptor received in ManagerNode: {fd=}"
            )

        # Open the socket
        self._sock = socket.fromfd(
            int(fd), family=socket.AF_UNIX, type=socket.SOCK_STREAM
        )
        self._sock.setblocking(True)
        os.close(int(fd))
        self._write_lock = threading.Lock()
        # Event stream to utilize socket
        self._event_stream = EventStream()

        # Parallel thread to read server responses
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

        # Child node mapping with access lock
        self._child_map = defaultdict(list)
        self._child_map_lock = threading.Lock()

        # Create the manager service
        self.create_service(LaunchNodeSrv, "launch_node", self._launch_node_callback)

    @property
    def child_map(self) -> dict[str, tuple[AckNode]]:
        """Returns an immutable view on the child_map dictionary."""
        with self._child_map_lock:
            return {k: tuple(v) for k, v in self._child_map.items()}

    def _reader_loop(self) -> None:
        """Simple socket reader loop to log node acks in parallel."""
        try:
            while True:
                # Read events from the socket
                chunk = self._sock.recv(1024)
                if not chunk:
                    break
                events = self._event_stream.read(chunk)

                with self._child_map_lock:
                    for e in events:
                        if not isinstance(e, AckNode):
                            self._logger.error(
                                f"Unexpected event response type {type(e).__name__} in ManagerNode"
                            )
                            continue

                        # Store acks mapped to the parent process
                        self._child_map[e.source].append(e)

        finally:
            try:
                self._sock.close()
            except Exception:
                pass

    def _write_event(self, event: Event) -> None:
        """Simple helper to send an event over the socket."""
        raw = self._event_stream.write(event)
        with self._write_lock:
            self._sock.sendall(raw)

    def _launch_node_callback(
        self, request: LaunchNodeSrv.Request, response: LaunchNodeSrv.Response
    ) -> LaunchNodeSrv.Response:
        """
        Callback function for the `launch_node` service. Will propagate a request to
        the launch server to instantiate a new node and respond with a success flag.
        """

        # Make a node action given the service request
        node_action = NodeAction(
            package=request.package,
            executable=request.executable,
            name=request.name if request.name != "" else None,
            arguments=request.arguments,
            output="screen",
        )

        # Send to launch service
        node_event = LaunchNodeEvent(node_action, source=request.source)
        self._write_event(node_event)

        # NOTE (trevor): Currently no support for gracefully handling a failed launch,
        #   will always return true (or crash)
        return response

    def spawn_node(self, action: NodeAction) -> None:
        """
        Spawn a node with this manager node as the dedicated parent.

        Args:
            action: The launch_ros action to create the desired node.
        """
        node_event = LaunchNodeEvent(action, source=self._name)
        self._write_event(node_event)

    def kill_node(self, target: str) -> bool:
        """
        Kill a node and all of its dependents. Returns a success flag and logs a
        warning if the node does not exist.

        Args:
            target: The name of the ROS2 node to terminate.
        """
        child_map = self.child_map
        if target not in child_map.keys():
            self._logger.warn(
                f"Unrecognized node ({target}) targetted for termination in ManagerNode"
            )
            return False

        # Kill target node and dependents
        self._kill_node_and_dependents(target, child_map)

        return True

    def _kill_node_and_dependents(
        self, target: str, child_map: dict[str, tuple[AckNode]]
    ):
        """
        Simple helper to iteratively terminate dependent nodes.
        Returns a list of all terminated nodes.
        """

        # Iterate and terminate dependent nodes first
        for child in child_map.get(target, []):
            self._kill_node_and_dependents(child.node_name, child_map)

        # Dependents are terminated, kill this targetted node
        kill_event = ShutdownProcess(process_matcher=matches_node_name(target))
        self._write_event(kill_event)

        with self._child_map_lock:
            # Remove the target from the map
            self._child_map.pop(target, None)

            # Remove target from its parent list if needed
            for children in self._child_map.values():
                for node_ack in children:
                    if node_ack.node_name == target:
                        children.remove(node_ack)
                        return


class ManagerNode(ManagerNodeMixin, Node):
    """
    A specialized node in the ROS graph.

    This subclassed Node allows all usual communication (publishers, subscribers,
    service, etc.), but also is able to launch other Nodes at runtime.
    """

    def __init__(self, *args, **kwargs):
        Node.__init__(self, *args, **kwargs)
        ManagerNodeMixin.__init__(self)
