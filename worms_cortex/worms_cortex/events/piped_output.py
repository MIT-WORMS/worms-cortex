from launch.events.process import RunningProcessEvent


class PipedOutput(RunningProcessEvent):
    """Emitted event when a piped process generates additional output."""

    name = "worms_cortex.events.PipedOutput"

    def __init__(self, *, data: bytes, **kwargs) -> None:
        """
        Create a `PipedOutput` event.

        Unmatched keyword arguments are passed to RunningProcessEvent, see it
        for details on those arguments.

        Args:
            data: Raw bytes received from the process
        """
        super().__init__(**kwargs)
        self.__data = data

    @property
    def data(self) -> bytes:
        return self.__data
