import json

from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, HistoryPolicy

from worms_mission_control.command_registry import CommandRegistry, CommandDescription
from worms_manager_msgs.msg import MissionCommand


class MissionControlNode(Node):
    """
    Abstract base for mission control nodes. Automatically registers all possible
    commands into the `registry` property. Use `publish_command` to send a mission
    control command to the system.
    """

    def __init__(self, node_name: str) -> None:
        super().__init__(node_name)
        self._pub = self.create_publisher(
            MissionCommand,
            "/mission_command",
            QoSProfile(
                depth=1,
                durability=DurabilityPolicy.TRANSIENT_LOCAL,
                history=HistoryPolicy.KEEP_LAST,
            ),
        )
        self._registry = CommandRegistry.load_all_registries()

    @property
    def registry(self) -> CommandRegistry:
        return self._registry

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
        msg.node_name = cmd.node_name
        msg.cmd.name = cmd.name
        msg.cmd.args_json = json.dumps(args)
        self._pub.publish(msg)
