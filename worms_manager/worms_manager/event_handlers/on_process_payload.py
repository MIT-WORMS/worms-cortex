from typing import Callable

import asyncio

from launch import Action, Event, LaunchContext
from launch.event_handlers.on_action_event_base import OnActionEventBase
from launch.some_entities_type import SomeEntitiesType

from ..events.process_payload import ProcessPayload
from ..events.serialize import EventStream


class OnProcessPayload(OnActionEventBase):
    """Helper class for handling raw output from a piped process via events."""

    def __init__(
        self,
        *,
        target_action: Callable[[Action], bool] | Action | None = None,
        on_output: SomeEntitiesType
        | Callable[[Event, LaunchContext], SomeEntitiesType | None],
        target_payload_cls: type[ProcessPayload] = ProcessPayload,
        **kwargs,
    ):
        """
        Create an `OnProcessPayload` event handler.

        Args:
            target_action: `ExecutePipedProcess` instance or callable to filter events
                from which process/processes to handle.
            on_output: Action to be done to handle the event or callable that is
                executed whenever an event is processed.
            target_payload_cls: Optional `ProcessPayload` class type to filter on.
        """
        from ..actions.execute_piped_process import ExecutePipedProcess

        if not issubclass(target_payload_cls, ProcessPayload):
            raise ValueError(
                "`target_payload_cls` in `OnProcessPayload` must be of type `ProcessPayload`"
            )
        self._queue = None
        super().__init__(
            action_matcher=target_action,
            on_event=on_output,
            target_event_cls=target_payload_cls,
            target_action_cls=ExecutePipedProcess,
            **kwargs,
        )

    def store_queue(self, queue: asyncio.Queue) -> None:
        """
        Populates the queue field to allow this handler to send events back to the
        child process. This is called automatically if the handler is passed to
        `ExecutePipedProcess` at initialization.

        Args:
            child_queue: `asyncio.Queue` for returning messages to a child process.
        """
        self._queue = queue

    def return_event(self, event: Event, context: LaunchContext) -> None:
        """
        Return an event to the child process if this handler was initialized on launch.
        This method will error if the handler was not passed to `ExecutePipedProcess`.

        Args:
            event: The event to return to the child process
        """
        if self._queue is None:
            raise RuntimeError(
                f"`{type(self).__name__}._return_event` was called, but the handler "
                "was not initialized with a queue at runtime."
            )
        raw = EventStream.write(event)
        try:
            self._queue.put_nowait(raw)
        except asyncio.QueueFull:
            context.__logger.warning(
                f"{type(event).__name__} event was dropped in `{type(self).__name__}` "
                "event handler due to insufficient queue size."
            )
