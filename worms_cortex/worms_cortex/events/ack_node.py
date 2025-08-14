from launch.event import Event


class AckNode(Event):
    """Basic event to be emitted into a client process to acknowledge a node launch."""

    name = "worms_cortex.events.AckNode"

    def __init__(self, *, node_name: str, pid: int, process_name: str):
        """
        Initialize an `AckNode` event.

        Args:
            node_name: The fully registered name of the node.
            pid: The process identifier.
            process_name: The unique process name.
        """
        self._node_name = node_name
        self._pid = pid
        self._process_name = process_name

    @property
    def node_name(self) -> str:
        return self._node_name

    @property
    def pid(self) -> int:
        return self._pid

    @property
    def process_name(self) -> str:
        return self._process_name
