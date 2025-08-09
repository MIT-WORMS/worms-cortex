from launch_ros.actions import Node

from .process_payload import ProcessPayload


class LaunchNode(ProcessPayload):
    """
    Client side event for a piped process to launch an additional node. Should be
    serialized with `SerializedEvent` before being transmitted.
    """

    name = "worms_cortex.events.LaunchNode"

    def __init__(self, node_action: Node):
        """
        Create a `LaunchNode` event.

        Args:
            node_action: An instance of `launch_ros.actions.Node`, not an `rclpy.Node`.
        """
        if not isinstance(node_action, Node):
            raise ValueError(
                "`LaunchNode` event expects a `Node` action from `launch_ros.actions`"
            )
        self._node_action = node_action

    @property
    def node(self) -> Node:
        return self._node_action
