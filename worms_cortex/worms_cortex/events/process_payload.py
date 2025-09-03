from typing import Dict, List, Optional, Text
from typing import TYPE_CHECKING

from launch.events.process import RunningProcessEvent

if TYPE_CHECKING:
    from launch.actions import ExecuteProcess


class EarlyAccessError(Exception):
    """
    Exception raised when accessing a member of `ProcessPayload` before it was
    supplied by the launch server.
    """

    def __init__(self, event: "ProcessPayload", property_name: str):
        super().__init__(
            f"Error accessing {property_name} in {type(event).__name__}. This "
            "field is supplied by the launch server and should not be accessed from "
            "the client."
        )


class ProcessPayload(RunningProcessEvent):
    """
    Client-side event for a piped process to generate arbitrary output. Should be
    inherited from and serialized with `SerializedEvent` before being transmitted.
    """

    name = "worms_cortex.events.ProcessPayload"

    def __init__(self):
        self._action = None
        self._name = None
        self._cmd = None
        self._cwd = None
        self._env = None
        self._pid = None

    def populate_process_args(
        self,
        *,
        action: "ExecuteProcess",
        name: Text,
        cmd: List[Text],
        cwd: Optional[Text],
        env: Optional[Dict[Text, Text]],
        pid: int,
    ) -> None:
        """
        Populate the process event arguments for this payload.

        Args:
            action: The ExecuteProcess action associated with the event
            name: The final name of the process instance, which is unique
            cmd: The final command after substitution expansion
            cwd: The final working directory after substitution expansion
            env: The final environment variables after substitution expansion
        """
        self._action = action
        self._name = name
        self._cmd = cmd
        self._cwd = cwd
        self._env = env
        self._pid = pid

    @property
    def action(self) -> "ExecuteProcess":
        """Getter for action."""
        if self._action is None:
            raise EarlyAccessError(self, "action")
        return self._action

    @property
    def execute_process_action(self) -> "ExecuteProcess":
        """Getter for execute_process_action."""
        if self._action is None:
            raise EarlyAccessError(self, "execute_process_action")
        return self._action

    @property
    def process_name(self) -> Text:
        """Getter for process_name."""
        if self._name is None:
            raise EarlyAccessError(self, "process_name")
        return self._name

    @property
    def cmd(self) -> List[Text]:
        """Getter for cmd."""
        if self._cmd is None:
            raise EarlyAccessError(self, "cmd")
        return self._cmd

    @property
    def cwd(self) -> Optional[Text]:
        """Getter for cwd."""
        if self._cwd is None:
            raise EarlyAccessError(self, "cwd")
        return self._cwd

    @property
    def env(self) -> Optional[Dict[Text, Text]]:
        """Getter for env."""
        if self._env is None:
            raise EarlyAccessError(self, "env")
        return self._env

    @property
    def pid(self) -> int:
        """Getter for pid."""
        if self._pid is None:
            raise EarlyAccessError(self, "pid")
        return self._pid
