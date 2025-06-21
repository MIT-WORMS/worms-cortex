from launch.event import Event


class RawPayload(Event):
    """Client-side event for a piped process to generate arbitrary output."""

    name = "worms_cortex.events.RawPayload"

    def __init__(self, *, data: bytes) -> None:
        """
        Create a `RawPayload` event.

        Args:
            data: Raw bytes received from the process
        """
        self.__data = data

    @property
    def data(self) -> bytes:
        return self.__data
