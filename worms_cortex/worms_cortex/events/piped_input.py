import struct

from launch.event import Event


class PipedInput(Event):
    """Emitted event from a piped child process to generate additional output."""

    name = "worms_cortex.events.PipedInput"

    def __init__(self, *, data: bytes) -> None:
        """
        Create a `PipedInput` event.

        Args:
            data: Raw bytes to be sent from the process
        """
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
