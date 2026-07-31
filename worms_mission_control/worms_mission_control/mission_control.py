import json
import re

import rclpy
from rclpy.node import Node
from rclpy.subscription import Subscription
from rclpy.qos import QoSProfile, DurabilityPolicy, HistoryPolicy

from worms_mission_control.command_registry import CommandRegistry, CommandDescription
from worms_manager_msgs.msg import MissionCommand
from worms_arthron_msgs.msg import NamedConfiguration

_TRANSIENT_LOCAL_QOS = QoSProfile(
    depth=1,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
)


class MissionControlNode(Node):
    """
    Abstract base for mission control nodes. Automatically registers all possible
    commands into the `registry` property. Use `publish_command` to send a mission
    control command to the system.
    """

    _CONFIG_RE = re.compile(r"^/[^/]+/named_configuration$")

    def __init__(self, node_name: str) -> None:
        super().__init__(node_name)
        self._pub = self.create_publisher(
            MissionCommand,
            "/mission_command",
            _TRANSIENT_LOCAL_QOS,
        )
        self._registry = CommandRegistry.load_all_registries()

        # Wait until a configuration topic is live
        self._config_topic: str | None = None
        self._config_sub: Subscription | None = None
        self._configuration: str | None = None
        while rclpy.ok():
            if self._connect_config():
                break
            rclpy.spin_once(self, timeout_sec=0.5)

        # Periodically check to see if the node has died
        self.create_timer(1.0, self._connect_config)

    @property
    def registry(self) -> CommandRegistry:
        return self._registry

    @property
    def configuration(self) -> str | None:
        return self._configuration

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

    def _config_callback(self, msg: NamedConfiguration) -> None:
        """Simple callback to store the current named configuration."""
        self._configuration = msg.config_name if msg.known_config else None

    def _connect_config(self) -> bool:
        """Verify connection to the config topic and swap if needed."""
        topic = self._find_config_topic()
        # Not discovered
        if topic is None:
            return False
        # Already connected
        if topic == self._config_topic:
            return True

        # Destroy the old sub and make a new one
        if self._config_sub is not None:
            self.destroy_subscription(self._config_sub)

        self._config_sub = self.create_subscription(
            NamedConfiguration,
            topic,
            self._config_callback,
            _TRANSIENT_LOCAL_QOS,
        )
        self._config_topic = topic
        return True

    def _find_config_topic(self) -> str | None:
        """Find and return the configuration topic if live."""
        canidates = [
            name
            for name, _ in self.get_topic_names_and_types()
            if self._CONFIG_RE.match(name)
        ]
        return min(canidates) if canidates else None
