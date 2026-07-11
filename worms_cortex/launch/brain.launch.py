from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node, PushRosNamespace

from worms_cortex.actions import ManagerNode


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument("namespace"),
            DeclareLaunchArgument("node_id"),
            DeclareLaunchArgument("cluster_name", default_value="raft_cluster"),
            DeclareLaunchArgument("foros_inspector", default_value="0"),
            GroupAction(
                [
                    PushRosNamespace(LaunchConfiguration("namespace")),
                    # Raft interface node responsible for leader election
                    Node(
                        package="foros",
                        executable="raft_interface_node",
                        name="raft_interface",
                        parameters=[
                            {
                                "cluster_name": LaunchConfiguration("cluster_name"),
                                "node_id": LaunchConfiguration("node_id"),
                            }
                        ],
                        additional_env={
                            "FOROS_INSPECTOR": LaunchConfiguration("foros_inspector"),
                        },
                        output="screen",
                    ),
                    # Brain node responsible for subroutine rollout
                    ManagerNode(
                        package="worms_cortex",
                        executable="brain_node",
                        name="brain",
                        parameters=[
                            {
                                "cluster_name": LaunchConfiguration("cluster_name"),
                                "node_id": LaunchConfiguration("node_id"),
                            }
                        ],
                        output="screen",
                    ),
                ]
            ),
        ]
    )
