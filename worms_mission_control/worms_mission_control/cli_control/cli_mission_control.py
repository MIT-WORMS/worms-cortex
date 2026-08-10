import threading
import select
import sys

import rclpy

from worms_mission_control.mission_control import MissionControlNode


class CLIMissionControlNode(MissionControlNode):
    """Basic command line interface for sending mission control commands."""

    _REFRESH = "__REFRESH__"

    def __init__(self) -> None:
        super().__init__("mission_control")

        # Track the prior config to know when to update the menu
        self._prev_configuration: str | None = None

        # Run the CLI in a continuous thread to not block ROS
        self._cli_thread = threading.Thread(target=self._cli_loop, daemon=True)
        self._cli_thread.start()

    def _interruptible_input(self, prompt: str = "") -> str | None:
        """Helper to collect and return input without permanently blocking."""

        print(prompt, end="", flush=True)

        try:
            while rclpy.ok():
                # Config changed before input, refresh the menu
                if self.configuration != self._prev_configuration:
                    self._prev_configuration = self.configuration
                    return self._REFRESH

                ready, _, _ = select.select([sys.stdin], [], [], 0.1)
                if ready:
                    line = sys.stdin.readline()

                    # EOF
                    if line == "":
                        return None

                    return line.rstrip("\n")

        except KeyboardInterrupt:
            rclpy.try_shutdown()

        return None

    def _cli_loop(self) -> None:
        """CLI loop to prompt for new mission control commands."""

        while rclpy.ok():
            # Valid keys for this configuration
            keys = [
                key
                for key, cmd in self.registry.items()
                if not cmd.compatible_configs
                or self.configuration in cmd.compatible_configs
            ]

            # Menu and input
            self._print_menu(keys)
            choice = self._interruptible_input("    > ")

            if choice == self._REFRESH:
                print()
                continue

            if choice is None:
                rclpy.try_shutdown()
                break

            choice = choice.strip().lower()

            if choice in ("q", "quit", "exit"):
                rclpy.try_shutdown()
                break

            # Verify the input
            idx = int(choice) - 1
            if not (0 <= idx < len(keys)):
                print("  Invalid choice.\n")
                continue

            # Get the args for this commnad
            args = self._prompt_command(keys[idx])

            # Publish the command
            self.publish_command(self.registry[keys[idx]], args)

    def _print_menu(self, keys: list[str]) -> None:
        """
        Print the command options to terminal.

        Args:
            keys ([str]): Command names in the registry
        """
        print("\n=== MISSION CONTROL ===")

        # Group the keys
        groups: dict[str, list[tuple[int, str]]] = {}
        for i, key in enumerate(keys):
            group = self.registry[key].group or "other"
            groups.setdefault(group, []).append((i + 1, key))

        # Print each entry
        for group, entries in groups.items():
            print(f"\n  [{group.upper()}]")
            for number, key in entries:
                print(
                    f"    {number}. {key.capitalize()}: {self.registry[key].description}"
                )

        print("\n  q. quit")

    def _prompt_command(self, key: str) -> dict:
        """
        Prompt for any arguments for the selected command.

        Args:
            key (str): The command name to prompt for
        """
        cmd = self.registry[key]
        print(f"\n-- {key.capitalize()} --")
        args = {}

        # Prompt for each potential arg
        for a in cmd.args:
            # Description with extras if applicable
            description = [a.description]
            if a.choices:
                description.append("/".join(a.choices))
            if not a.required and a.default is not None:
                description.append(f"default: {a.default}")
            prompt = f"  {a.name} ({', '.join(description)}): "

            while True:
                print(prompt)
                raw = self._interruptible_input("    > ")

                # No value provided
                if not raw:
                    # Just use default
                    if not a.required:
                        args[a.name] = a.default
                        break

                    print("    Required — please enter a value.")
                    continue

                raw = raw.strip()

                # Invalid choice
                if a.choices and raw not in a.choices:
                    print(f"    Must be one of: {', '.join(a.choices)}")
                    continue

                # Try to cast the input
                try:
                    args[a.name] = a.type(raw)
                    break
                except (ValueError, TypeError):
                    print(f"    Expected {a.type.__name__}.")

        return args


def main(args=None):
    rclpy.init(args=args)
    node = CLIMissionControlNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
