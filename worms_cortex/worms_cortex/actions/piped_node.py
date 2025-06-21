from launch_ros.actions import Node

from .execute_piped_process import ExecutePipedProcess


class PipedNode(Node, ExecutePipedProcess):  # type: ignore
    """
    Action that executes a ROS node with additional piped output. See
    `ExecutePipedProcess` for more details.
    """
