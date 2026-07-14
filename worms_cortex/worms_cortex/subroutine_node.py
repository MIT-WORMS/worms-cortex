import json
from abc import abstractmethod

from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, HistoryPolicy

from worms_mission_control.command_registry import CommandRegistry
from worms_cortex_interface.msg import SubroutineCommand


class SubroutineNode(Node):
    """
    Abstract base class for all subroutine nodes. The child class should register
    any compatible commands in a `CommandRegistry` within the package, and then
    pass that registry into the init for validation. The child class should
    also implement `on_command()`, which will receive the args detailed in
    the registry from mission command like:

    .. code-block:: python

        def on_command(self, command: str, args: dict):
            if command == 'stop':
                ...
            elif command == 'walk':
                direction = args['direction']
                distance  = args['distance_m']
                ...
            elif command == 'turn':
                degrees = args['degrees']
                ...
    """

    def __init__(self, node_name: str, registry: CommandRegistry) -> None:
        """
        Extended to set up communication with a parent node.

        Args:
            registry (CommandRegistry): A collection of valid commands
                accepted by this node
        """
        super().__init__(node_name)
        self._registry = registry

        self.create_subscription(
            SubroutineCommand,
            "~/subroutine_command",
            self._on_command_msg,
            QoSProfile(
                depth=1,
                durability=DurabilityPolicy.TRANSIENT_LOCAL,
                history=HistoryPolicy.KEEP_LAST,
            ),
        )

    def _on_command_msg(self, msg: SubroutineCommand) -> None:
        """
        Callback for new subroutine command from the parent node.

        Args:
            msg (SubroutineCommand): The new command to be validated
        """
        try:
            raw_args = json.loads(msg.args_json)
        except json.JSONDecodeError as e:
            self.get_logger().error(f"Invalid raw_args: {e}")
            return

        validated_args = self._validate(msg.name, raw_args)
        if validated_args is not None:
            self.on_command(msg.name, validated_args)

    def _validate(self, command: str, raw: dict) -> dict | None:
        """
        Validate and cast raw args based on the registry.

        Args:
            command (str): The name of the command to validate
            raw (dict): The dictionary loaded from the message

        Returns:
            out (dict | None): A validated and cast dictionary if successful
        """
        description = self._registry.get(command)
        if description is None:
            self.get_logger().error(f"Unknown command: {command!r}")
            return None

        result = {}
        errors: list[str] = []

        for a in description.args:
            # Arg not present, default if possible
            if a.name not in raw:
                if a.required:
                    errors.append(f"{a.name!r} is required")
                else:
                    result[a.name] = a.default
                continue

            # Try to cast the value to its expected type
            try:
                value = a.type(raw[a.name])
            except (ValueError, TypeError):
                errors.append(
                    f"{a.name!r}: cannot cast {raw[a.name]!r} to {a.type.__name__}"
                )
                continue

            # Invalid choice for limited arg
            if a.choices is not None and value not in a.choices:
                errors.append(f"{a.name!r}: {value!r} must be one of {a.choices}")
                continue

            # Properly validated
            result[a.name] = value

        if errors:
            self.get_logger().error(
                f"Command {command!r} rejected: " + "; ".join(errors)
            )
            return None

        return result

    @abstractmethod
    def on_command(self, command: str, args: dict) -> None:
        """
        Called with a validated argument dictionary when a new command arrives
        from the parent node.

        Args:
            command (str): The name of this command in the registry
            args (dict): A dictionary of arguments outlined in the args field
                of the registry
        """
        ...
