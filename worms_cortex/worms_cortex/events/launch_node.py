from launch_ros.actions import Node

from .process_payload import ProcessPayload


class LaunchNode(ProcessPayload):
    """
    Client side event for a piped process to launch an additional node. Should be
    serialized with `SerializedEvent` before being transmitted.
    """

    name = "worms_cortex.events.LaunchNode"

    def __init__(self, node_action: Node, *, source: str):
        """
        Create a `LaunchNode` event.

        Args:
            node_action: An instance of `launch_ros.actions.Node`, not an `rclpy.Node`.
            source: An identifying string to map acknowledgements to launch requests.
        """
        if not isinstance(node_action, Node):
            raise ValueError(
                "`LaunchNode` event expects a `Node` action from `launch_ros.actions`"
            )
        self._node_action = node_action
        self._source = source

    @property
    def node(self) -> Node:
        return self._node_action

    @property
    def source(self) -> str:
        return self._source
