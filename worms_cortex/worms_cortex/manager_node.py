import os
import socket

from rclpy import Node

from launch_ros.actions import Node as NodeAction

from worms_cortex.actions import SOCKET_ENVIRON
from worms_cortex.events import LaunchNode as LaunchNodeEvent
from worms_cortex.events.serialize import SerializedEvent
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

        # Create the manager service
        self.create_service(LaunchNodeSrv, "launch_node", self._launch_node_callback)

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

        # Package into an event and serialize
        node_event = LaunchNodeEvent(node_action)
        message = SerializedEvent(node_event)

        # Send to launch service
        self._sock.send(message.encode())

        # TODO (trevor): Set up response handler in launch service

        # NOTE (trevor): Currently no support for gracefully handling a failed launch,
        #   will always return true (or crash) but waits for it to launch to return
        return response


class ManagerNode(Node):
    """
    A specialized node in the ROS graph.

    This subclassed Node allows all usual communication (publishers, subscribers,
    service, etc.), but also is able to launch other Nodes at runtime.
    """

    # TODO: Finish
