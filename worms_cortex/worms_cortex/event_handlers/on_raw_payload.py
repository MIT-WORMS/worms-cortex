from typing import Callable

from launch import Action, Event, LaunchContext
from launch.event_handlers.on_action_event_base import OnActionEventBase
from launch.some_entities_type import SomeEntitiesType

from ..actions.execute_piped_process import ExecutePipedProcess
from ..events.raw_payload import RawPayload


class OnRawPayload(OnActionEventBase):
    """Helper class for handling raw output from a piped process via events."""

    def __init__(
        self,
        *,
        target_action: Callable[[Action], bool] | Action | None = None,
        on_output: SomeEntitiesType
        | Callable[[Event, LaunchContext], SomeEntitiesType | None],
        target_payload_cls: type[RawPayload] = RawPayload,
        **kwargs,
    ):
        """
        Create an `OnRawPayload` event handler.

        Args:
            target_action: `ExecutePipedProcess` instance or callable to filter events
                from which process/processes to handle.
            on_output: Action to be done to handle the event or callable that is
                executed whenever an event is processed.
            target_payload_cls: Optional `RawPayload` class type to filter on.
        """
        if not issubclass(target_payload_cls, RawPayload):
            raise ValueError(
                "`target_payload_cls` in `OnRawPayload` must be of type `RawPayload`"
            )
        super().__init__(
            action_matcher=target_action,
            on_event=on_output,
            target_event_cls=target_payload_cls,
            target_action_cls=ExecutePipedProcess,
            **kwargs,
        )
