import json
from importlib.metadata import entry_points

from rclpy.node import Node

from worms_mission_control.command_registry import CommandRegistry, CommandDescription
from worms_cortex_interface.msg import MissionCommand


class MissionControlNode(Node):
    """
    Abstract base for mission control nodes. Automatically registers all possible
    commands into the `registry` property. Use `publish_command` to send a mission
    control command to the system.
    """

    def __init__(self, node_name: str) -> None:
        super().__init__(node_name)
        self._pub = self.create_publisher(MissionCommand, "/mission_command", 10)
        self._registry = self.load_all_registries()

    @property
    def registry(self) -> CommandRegistry:
        return self._registry

    def load_all_registries(self) -> CommandRegistry:
        """
        Load the command registries of installed packages.

        Returns:
            registry (CommandRegistry): The merged registry of all installed packages
        """
        merged = CommandRegistry()
        for ep in entry_points(group="mission_control.subroutine_registries"):
            pkg_registry = ep.load()

            # Make sure the entry point is valid
            if not isinstance(pkg_registry, CommandRegistry):
                raise ValueError(f"Invalid command registry at {ep.group} = {ep.value}")

            for _, cmd in pkg_registry.items():
                merged.register(cmd)

        return merged

    def publish_command(self, cmd: CommandDescription, args: dict) -> None:
        """
        Publish a mission control command.

        Args:
            cmd (CommandDescription): The command to run
            args (dict): A dictionary of arguments to pass to the subroutine
        """
        msg = MissionCommand()
        msg.package = cmd.package
        msg.executable = cmd.executable
        msg.cmd.name = cmd.name
        msg.cmd.args_json = json.dumps(args)
        self._pub.publish(msg)
