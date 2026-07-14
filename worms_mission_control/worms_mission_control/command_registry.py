from dataclasses import dataclass, field
from collections.abc import ItemsView, KeysView
from typing import Any, Iterator


@dataclass
class CommandArgument:
    """A single argument for a SubroutineNode"""

    name: str
    """The key for this argument"""
    type: type
    """The datatype of this field"""
    description: str
    """Description of the field"""
    required: bool = True
    """True if it must be provided"""
    default: Any = None
    """A default value to be used if not required"""
    choices: list[str] | None = None
    """A finite set of choices for this argument"""


@dataclass
class CommandDescription:
    """A command that can be run through mission control."""

    name: str
    """A unique name for this command"""
    package: str
    """ROS package containing the SubroutineNode to launch"""
    executable: str
    """ROS entry point name for the SubroutineNode"""
    node_name: str
    """ROS node name for the SubroutineNode"""
    description: str
    """Description of the command"""
    group: str = ""
    """Group this command belongs to, just for organization"""
    args: list[CommandArgument] = field(default_factory=list)
    """A list of args that will be passed to this subroutine"""


class CommandRegistry:
    """
    A collection of mission control commands. Create an instance in the
    desired package and register new commands with:

    .. code-block:: python

        REGISTRY = CommandRegistry()
        REGISTRY.register(
            CommandDescription(
                name="walk",
                package="walking_pkg",
                executable="walking_node",
                description="Walk forward a fixed distance",
                group="mobility",
                args=[
                    CommandArgument(
                        name="direction",
                        type=str,
                        description="Which direction to walk",
                        choices=["forward", "backward"],
                    ),
                    CommandArgument(
                        name="distance_m",
                        type=float,
                        description="Distance in meters",
                    ),
                ],
            )
        )

    After creating the registry within the package, register it as an entry point
    in `setup.py` with:

    .. code-block:: python
        entry_points={
            'mission_control.subroutine_registries': [
                'walking_registry = walking_pkg.registry:REGISTRY',
            ],
        },

    """

    def __init__(self):
        self._commands: dict[str, CommandDescription] = {}

    def register(self, command: CommandDescription) -> "CommandRegistry":
        """
        Register a new command within the registry.

        Args:
            command (CommandDescription): The command to register

        Returns:
            self (CommandRegistry): This instance, for function chaining
        """
        if command.name in self._commands:
            raise ValueError(f"Command {command.name!r} already registered")
        self._commands[command.name] = command
        return self

    def __getitem__(self, key: str) -> CommandDescription:
        return self._commands[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._commands)

    def keys(self) -> KeysView[str]:
        return self._commands.keys()

    def items(self) -> ItemsView[str, CommandDescription]:
        return self._commands.items()

    def get(self, key: str, default: Any | None = None) -> CommandDescription | None:
        return self._commands.get(key, default)
