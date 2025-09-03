from typing import TYPE_CHECKING

from worms_cortex_interface.srv import LaunchNode_Request as _BaseLaunchNode_Request
from worms_cortex_interface.srv import LaunchNode as _BaseLaunchNode

if TYPE_CHECKING:
    from rclpy.node import Node


class LaunchNode_Request(_BaseLaunchNode_Request):
    def __init__(self, *, node: Node, **kwargs):
        """
        Message class 'LaunchNode_Request'.

        Subclassed to enforce proper initialization of the source field. Any attempts
        to modify `source` will raise an error.
        """
        super().__init__(source=node.get_fully_qualified_name(), **kwargs)

    @_BaseLaunchNode_Request.source.setter
    def source(self, value):
        raise NotImplementedError(
            "The source of a LaunchNode service request cannot be changed after "
            "initialization."
        )


class LaunchNode(_BaseLaunchNode):
    from .launch_node import LaunchNode_Request as Request
    from worms_cortex_interface.srv._launch_node import LaunchNode_Response as Response
    from worms_cortex_interface.srv._launch_node import LaunchNode_Event as Event
