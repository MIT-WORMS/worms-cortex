import pickle
import struct

from launch.event import Event

HEADER_SIZE = 4
"""Length of a package header in bytes."""

HEADER_FORMAT = ">I"
"""Packaged format of a header for use in `struct.pack` or `struct.unpack`."""


class SerializedEvent:
    """
    Helper class to serialize events for emission into a `ExecutePipedProcess` instance
    """

    def __init__(self, event: Event):
        """
        Create a `SerializedEvent` event to be sent over a socket.

        Args:
            event: An event instance to propagate to the parent
        """
        if not isinstance(event, Event):
            raise TypeError(
                f"Invalid event type {type(event).__name__} in SerializedEvent."
            )

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
        return struct.pack(HEADER_FORMAT, len(self._data))

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


class DeserializedEvent:
    """
    Helper class to deserialize events from a `ExecutePipedProcess` instance.
    """

    def __init__(self, raw_payload: bytes):
        """
        Create a `DeserializedEvent` event to be received over a socket.

        Args:
            raw_payload: Payload bytes as received from the socket (excludes header)
        """

        # Try to deserialize the event
        try:
            event = pickle.loads(raw_payload)
        except Exception as e:
            raise ValueError(f"Failed to deserialize event: {e}") from e

        if not isinstance(event, Event):
            raise TypeError(
                f"Invalid event type {type(event).__name__} in DeserializedEvent."
            )

        self._event = event
        self._raw_payload = raw_payload

    @property
    def event(self) -> Event:
        return self._event

    @property
    def raw(self) -> bytes:
        return self._raw_payload


class EventStream:
    """
    Helper class to handle interfacing with a socket to send and receive events.
    """

    def __init__(self):
        """Initialize an `EventStream` to interface with a socket."""
        self._buffer = b""
        self._expected_length = None

    def read(self, chunk: bytes) -> list[Event]:
        """
        Update the internal buffer with a new chunk of data. Returns the event if
        a full event has been unpacked.

        Args:
            chunk: The raw bytes as received from a `read` call.

        Returns:
            A potentially empty iterable of events

        Raises:
            struct.error: On malformed payload header
            ValueError: When failing to deserialize the event itself
            TypeError: If the deserialized payload is not an `Event` object
        """
        if not chunk:
            return []

        self._buffer += chunk
        events = []
        while True:
            # Attempt to extract payload length
            if self._expected_length is None:
                # Not enough data for package length
                if len(self._buffer) < HEADER_SIZE:
                    break

                # Unpack package length, error if malformed
                try:
                    self._expected_length = struct.unpack(
                        HEADER_FORMAT, self._buffer[:HEADER_SIZE]
                    )[0]
                    self._buffer = self._buffer[HEADER_SIZE:]
                except struct.error as e:
                    e.add_note("Malformed payload header in EventStream")
                    raise e

            # Not enough data for payload
            if len(self._buffer) < self._expected_length:
                break

            # Unpack payload
            payload = self._buffer[: self._expected_length]
            self._buffer = self._buffer[self._expected_length :]
            self._expected_length = None

            # Deserialize the event (errors internally)
            deserialized = DeserializedEvent(payload)
            events.append(deserialized.event)

        return events

    @staticmethod
    def write(event: Event) -> bytes:
        serialized = SerializedEvent(event)
        return serialized.encode()
