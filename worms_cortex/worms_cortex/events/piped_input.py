import pickle
import struct

from launch.event import Event


class PipedInput(Event):
    """Emitted client-side event for a child process to propagate arbitrary events."""

    name = "worms_cortex.events.PipedInput"

    def __init__(self, *, event: Event) -> None:
        """
        Create a `PipedInput` event to be sent from the child process.

        Args:
            event: An event instance to propagate to the parent
        """
        if not isinstance(event, Event):
            raise TypeError(f"Invalid event type {type(event).__name__} in PipedInput.")

        # Try to serialize the event
        try:
            data = pickle.dumps(event)
        except Exception as e:
            raise ValueError(f"Failed to serialize event: {e}") from e

        self.__event = event
        self.__data = data

    def __bytes__(self) -> bytes:
        return self.message

    @property
    def header(self) -> bytes:
        return struct.pack(">I", len(self.__data))

    @property
    def payload(self) -> bytes:
        return self.__data

    @property
    def message(self) -> bytes:
        return self.header + self.payload

    @property
    def event(self) -> Event:
        return self.__event
