from typing import List
from enum import StrEnum, auto

from rclpy.node import Node
from rclpy.context import Context
from rclpy.parameter import Parameter

from launch_ros.utilities import prefix_namespace


class SubsystemType(StrEnum):
    """Valid subsystem types for a `SubsystemNode`"""

    DRIVER = auto()
    CONTROLLER = auto()
    OBSERVER = auto()


class SubsystemNode(Node):
    """
    An abstract ROS2 Node that represents any singular component of a larger task.

    These are broken into three categories:
        Drivers (e.g. a motor interface)
        Controllers (e.g. a PID controller)
        Observers (e.g. a high-pass filter)
    """

    def __init__(
        self,
        node_name: str,
        node_type: SubsystemType,
        *,
        context: Context | None = None,
        cli_args: List[str] | None = None,
        namespace: str | None = None,
        use_global_arguments: bool = True,
        enable_rosout: bool = True,
        start_parameter_services: bool = True,
        parameter_overrides: List[Parameter] | None = None,
        allow_undeclared_parameters: bool = False,
        automatically_declare_parameters_from_overrides: bool = False,
        enable_logger_service: bool = False,
    ) -> None:
        """
        Create a Subsystem Node.

        Args:
            node_name: A name to give to this node. Validated by `validate_node_name`.
            node_type: The type of subsystem being created.
            context: The context to be associated with, or `None` for the default
                global context.
            cli_args: A list of strings of command line args to be used only by this
                node. These arguments are used to extract remappings used by the node
                and other ROS specific settings, as well as user defined non-ROS
                arguments.
            namespace: The namespace to which relative topic and service names will be
                prefixed. Validated by `validate_namespace`.
            use_global_arguments: `False` if the node should ignore process-wide
                command line args.
            enable_rosout: `False` if the node should ignore rosout logging.
            start_parameter_services: `False` if the node should not create parameter
                services.
            parameter_overrides: A list of overrides for initial values for parameters
                declared on the node.
            allow_undeclared_parameters: True if undeclared parameters are allowed.
                This flag affects the behavior of parameter-related operations.
            automatically_declare_parameters_from_overrides: If True, the "parameter
                overrides" will be used to implicitly declare parameters on the node
                during creation.
            enable_logger_service: `True` if ROS2 services are created to allow
                external nodes to get and set logger levels of this node. Otherwise,
                logger levels are only managed locally. That is, logger levels cannot
                be changed remotely.
        """
        # Store the node type
        self._subsystem_type = node_type

        # Pass arguments to underlying node
        super().__init__(
            node_name=node_name,
            context=context,
            cli_args=cli_args,
            namespace=prefix_namespace(f"/{node_type.name}", namespace),
            use_global_arguments=use_global_arguments,
            enable_rosout=enable_rosout,
            start_parameter_services=start_parameter_services,
            parameter_overrides=parameter_overrides,
            allow_undeclared_parameters=allow_undeclared_parameters,
            automatically_declare_parameters_from_overrides=automatically_declare_parameters_from_overrides,
            enable_logger_service=enable_logger_service,
        )
