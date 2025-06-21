from typing import Callable

from launch import Action, Event, LaunchContext
from launch.event_handlers.on_action_event_base import OnActionEventBase
from launch.some_entities_type import SomeEntitiesType

from ..actions import ExecutePipedProcess
from ..events import RawPayload


class OnRawPayload(OnActionEventBase):
    """Helper class for handling raw output from a piped process via events."""

    def __init__(
        self,
        *,
        target_action: Callable[[Action], bool] | Action | None = None,
        on_output: SomeEntitiesType
        | Callable[[Event, LaunchContext], SomeEntitiesType | None],
        **kwargs,
    ) -> None:
        """
        Create an `OnRawPayload` event handler.

        Args:
            target_action: `ExecutePipedProcess` instance or callable to filter events
                from which process/processes to handle.
            on_output: Action to be done to handle the event or callable that is
                executed whenever an event is processed.
        """

        super().__init__(
            action_matcher=target_action,
            on_event=on_output,
            target_event_cls=RawPayload,
            target_action_cls=ExecutePipedProcess,
            **kwargs,
        )
