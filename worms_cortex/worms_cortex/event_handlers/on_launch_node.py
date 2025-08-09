from typing import Callable

from launch import Action, LaunchContext
from launch_ros.actions import Node

from .on_process_payload import OnProcessPayload
from ..events.launch_node import LaunchNode


class OnLaunchNode(OnProcessPayload):
    """
    Helper class for handling specifically `LaunchNode` events from a piped process.
    """

    def __init__(
        self, *, target_action: Callable[[Action], bool] | Action | None = None
    ):
        """
        Create an `OnLaunchNode` event handler.

        Args:
            target_action: `ExecutePipedProcess` instance or callable to filter events
                from which process/processes to handle.
        """
        super().__init__(
            target_action=target_action,
            on_output=self._on_launch_node_event,  # type: ignore[arg-type]
            target_payload_cls=LaunchNode,
        )

    def _on_launch_node_event(self, event: LaunchNode, context: LaunchContext) -> Node:
        return event.node
