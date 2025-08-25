from launch_ros.actions import Node

from .execute_piped_process import ExecutePipedProcess


class PipedNode(Node, ExecutePipedProcess):  # type: ignore
    """
    Action that executes a ROS node with additional piped output. The event handlers
    for this output should be registered with the `payload_handlers` kwarg. See
    `ExecutePipedProcess` for more details.
    """
