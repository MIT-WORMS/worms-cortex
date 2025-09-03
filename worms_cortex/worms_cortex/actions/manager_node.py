from typing import Iterable

from ..event_handlers import OnProcessPayload, OnLaunchNode
from .piped_node import PipedNode


class ManagerNode(PipedNode):
    """
    Convenience action wrapper around `PipedNode` to automatically include a
    payload handler for Node actions. Additional handlers can be included with the
    `additional_payload_handlers` kwarg.
    """

    def __init__(
        self,
        *,
        additional_payload_handlers: Iterable[OnProcessPayload] | None = None,
        **kwargs,
    ):
        payload_handlers = (
            []
            if additional_payload_handlers is None
            else list(additional_payload_handlers)
        )
        payload_handlers.append(OnLaunchNode(target_action=self))
        super().__init__(payload_handlers=payload_handlers, **kwargs)
