from typing import Callable

from launch import Action, LaunchContext
from launch.events.process import ProcessStarted
from launch.event_handlers import OnProcessStart
from launch_ros.actions import Node

from .on_process_payload import OnProcessPayload
from ..events import LaunchNode, AckNode


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
            on_output=self._on_launch_node_event,  # type: ignore [narrowing type to target action]
            target_payload_cls=LaunchNode,
        )

    def _on_launch_node_event(self, event: LaunchNode, context: LaunchContext) -> Node:
        node_action = event.node

        # Make a one-time event handler to acknowledge the node launching
        ack_node_launch = OnProcessStart(
            target_action=node_action,
            on_start=lambda e, c: self._on_ack_node_launch(e, c, event.source),
            handle_once=True,
        )
        context.register_event_handler(ack_node_launch)

        return node_action

    def _on_ack_node_launch(
        self, event: ProcessStarted, context: LaunchContext, source: str
    ) -> None:
        ack = AckNode(
            source,
            node_name=event.action.node_name,  # type: ignore [targetted on a Node action]
            pid=event.pid,
            process_name=event.name,
        )
        self._return_event(ack, context)
