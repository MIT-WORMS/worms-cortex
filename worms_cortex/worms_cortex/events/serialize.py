import pickle
import struct

from launch.event import Event


class SerializedEvent:
    """
    Helper class to serialize events for emission into a `ExecutePipedProcess` instance
    """

    def __init__(self, event: Event) -> None:
        """
        Create a `SerializedEvent` event to be sent from the child process.

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

        self._event = event
        self._data = data

    def __bytes__(self) -> bytes:
        return self.message

    @property
    def header(self) -> bytes:
        return struct.pack(">I", len(self._data))

    @property
    def payload(self) -> bytes:
        return self._data

    @property
    def message(self) -> bytes:
        return self.header + self.payload

    @property
    def event(self) -> Event:
        return self._event

    def encode(self) -> bytes:
        """Encode this event for emission into the child process socket."""
        return self.message
