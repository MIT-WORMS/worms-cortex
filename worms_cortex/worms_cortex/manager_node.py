import os
import socket
import threading
from collections import defaultdict

from rclpy import Node

from launch_ros.actions import Node as NodeAction

from worms_cortex.actions import SOCKET_ENVIRON
from worms_cortex.events import LaunchNode as LaunchNodeEvent
from worms_cortex.events import AckNode
from worms_cortex.events.serialize import EventStream
from worms_cortex_interface.srv import LaunchNode as LaunchNodeSrv


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

        # Try to retrieve the communications socket
        fd = os.environ.get(SOCKET_ENVIRON, None)
        # TODO (trevor): Reword if we add support for ros2 run
        if fd is None:
            raise RuntimeError(
                "Failed to retrieve launch service file descriptor. ManagerNodes must"
                "be launched using `ros2 launch` with the `PipedNode` action."
            )
        if not fd.isnumeric():
            raise RuntimeError(
                f"Malformed file descriptor received in ManagerNode: {fd=}"
            )

        # Open the socket
        self._sock = socket.fromfd(
            int(fd), family=socket.AF_UNIX, type=socket.SOCK_STREAM
        )
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
        # TODO (trevor): Force service callers to include their node name for source
        node_event = LaunchNodeEvent(node_action, source="temp")
        raw = self._event_stream.write(node_event)
        with self._write_lock:
            self._sock.sendall(raw)

        # NOTE (trevor): Currently no support for gracefully handling a failed launch,
        #   will always return true (or crash)
        return response


class ManagerNode(ManagerNodeMixin, Node):
    """
    A specialized node in the ROS graph.

    This subclassed Node allows all usual communication (publishers, subscribers,
    service, etc.), but also is able to launch other Nodes at runtime.
    """

    def __init__(self, *args, **kwargs):
        Node.__init__(self, *args, **kwargs)
        ManagerNodeMixin.__init__(self)
