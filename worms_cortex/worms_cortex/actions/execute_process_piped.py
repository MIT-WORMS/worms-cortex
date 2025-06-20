from typing import Dict, List, Iterable

import os
import asyncio
import socket
import traceback
from contextlib import suppress

from launch.launch_description_entity import LaunchDescriptionEntity
from osrf_pycommon.process_utils import async_execute_process

from launch import LaunchContext
from launch.actions import ExecuteProcess, ExecuteLocal
from launch.events.process import ProcessStarted, ProcessExited
from launch.conditions import evaluate_condition_expression
from launch.frontend import expose_action
from launch.utilities import normalize_to_list_of_substitutions
from launch.some_substitutions_type import SomeSubstitutionsType


@expose_action("piped_executable")
class ExecutePipedProcess(ExecuteProcess):
    """
    Action that executes a process and sets up a communication pipe with it. The child
    process can then emit events in the parent process through this pipe.
    """

    def __init__(
        self,
        *,
        cmd: Iterable[SomeSubstitutionsType],
        handler,  # TODO (trevor): Make an abstract base class for this
        prefix: SomeSubstitutionsType | None = None,
        name: SomeSubstitutionsType | None = None,
        cwd: SomeSubstitutionsType | None = None,
        env: Dict[SomeSubstitutionsType, SomeSubstitutionsType] | None = None,
        additional_env: Dict[SomeSubstitutionsType, SomeSubstitutionsType]
        | None = None,
        **kwargs,
    ) -> None:
        """
        Extends the `ExecuteProcess` action allowing the child process to emit events.

        Args:
            # TODO (trevor): Indicate typehint here
            handler: The `EventHandler` to manage events from the child process.
        """
        super().__init__(
            cmd=cmd,
            prefix=prefix,
            name=name,
            cwd=cwd,
            env=env,
            additional_env=additional_env,
            **kwargs,
        )
        self.__extra_handler = handler

    class __ProcessProtocol(ExecuteProcess.__ProcessProtocol):
        """Subclassed to include an additional communication socket."""

        def __init__(
            self,
            action: ExecuteLocal,
            context: LaunchContext,
            process_event_args: Dict,
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
            **kwargs,
        ) -> None:
            super().__init__(action, context, process_event_args, **kwargs)
            self.__reader = reader
            self.__writer = writer
            self.__watch_task = None

        def connection_made(self, transport: asyncio.SubprocessTransport) -> None:
            """Called when a connection is made."""
            super().connection_made(transport)
            self.__watch_task = asyncio.create_task(self.__watch_additional_socket())

        def connection_lost(self, exc: Exception | None):
            """Called when a connection is lost or closed."""
            if self.__watch_task:
                self.__watch_task.cancel()
                asyncio.create_task(self.__cleanup_watch_task())

            if self.__writer:
                self.__writer.close()
                asyncio.create_task(self.__writer.wait_closed())

            super().connection_lost(exc)

        def on_additional_socket_received(self, data: bytes) -> None:
            """Custom logic for handling additional data from the process."""
            # TODO (trevor): Set up a custom event to emit
            pass

        async def __cleanup_watch_task(self) -> None:
            """Waits for the watch task to exit cleanly."""
            if not self.__watch_task:
                return

            with suppress(asyncio.CancelledError):
                await self.__watch_task
            self.__watch_task = None

        async def __watch_additional_socket(self) -> None:
            """
            Watches the additional process socket and passes data to
            `on_additional_socket_received` if anything is sent.
            """
            while not self.__reader.at_eof():
                # TODO (trevor): Implications of reading 1024 bytes?
                data = await self.__reader.read(1024)
                if data:
                    self.on_additional_socket_received(data)

    async def __execute_process(self, context: LaunchContext) -> None:
        process_event_args = self.__process_event_args
        if process_event_args is None:
            raise RuntimeError("process_event_args unexpectedly None")

        # Open an additional communication socket
        server_sock, subprocess_sock = socket.socketpair()
        server_sock.setblocking(False)
        subprocess_sock.setblocking(False)
        os.set_inheritable(subprocess_sock.fileno(), True)

        # Log process details
        cmd = process_event_args["cmd"]
        cwd = process_event_args["cwd"]
        env = process_event_args["env"]
        if self.__log_cmd:
            self.__logger.info(
                "process details: cmd='{}', cwd='{}', custom_env?={}".format(
                    " ".join(filter(lambda part: part.strip(), cmd)),
                    cwd,
                    "True" if env is not None else "False",
                )
            )

        # Inject additional socket fd into env
        fd_dict = {"_SOCKET_FD": str(subprocess_sock.fileno())}
        env = env | fd_dict if env else fd_dict

        # Emulate tty resolution
        emulate_tty = self.__emulate_tty
        if "emulate_tty" in context.launch_configurations:
            emulate_tty = evaluate_condition_expression(
                context,
                normalize_to_list_of_substitutions(
                    context.launch_configurations["emulate_tty"]
                ),
            )

        # Execute process async
        try:
            reader, writer = await asyncio.open_unix_connection(sock=server_sock)
            transport, self._subprocess_protocol = await async_execute_process(
                lambda **kwargs: self.__ProcessProtocol(
                    self, context, process_event_args, reader, writer, **kwargs
                ),
                cmd=cmd,
                cwd=cwd,
                env=env,
                shell=self.__shell,
                emulate_tty=emulate_tty,
                stderr_to_stdout=False,
            )
        except Exception:
            self.__logger.error(
                "exception occurred while executing process:\n{}".format(
                    traceback.format_exc()
                )
            )
            server_sock.close()
            subprocess_sock.close()
            self.__cleanup()
            return

        pid = transport.get_pid()
        self._subprocess_transport = transport

        # Process start behavior
        await context.emit_event(ProcessStarted(**process_event_args))

        # Process exit behavior
        returncode = await self._subprocess_protocol.complete  # type: ignore
        if returncode == 0:
            self.__logger.info("process has finished cleanly [pid {}]".format(pid))
        else:
            self.__logger.error(
                "process has died [pid {}, exit code {}, cmd '{}'].".format(
                    pid, returncode, " ".join(filter(lambda part: part.strip(), cmd))
                )
            )
        await context.emit_event(
            ProcessExited(returncode=returncode, **process_event_args)
        )
        # respawn the process if necessary
        if (
            not context.is_shutdown
            and self.__shutdown_future is not None
            and not self.__shutdown_future.done()
            and self.__respawn
            and (
                self.__respawn_max_retries < 0
                or self.__respawn_retries < self.__respawn_max_retries
            )
        ):
            # Increase the respawn_retries counter
            self.__respawn_retries += 1
            if self.__respawn_delay is not None and self.__respawn_delay > 0.0:
                # wait for a timeout(`self.__respawn_delay`) to respawn the process
                # and handle shutdown event with future(`self.__shutdown_future`)
                # to make sure `ros2 launch` exit in time
                await asyncio.wait(
                    (self.__shutdown_future,), timeout=self.__respawn_delay
                )
            if not self.__shutdown_future.done():
                context.asyncio_loop.create_task(self.__execute_process(context))  # type: ignore
                return
        server_sock.close()
        subprocess_sock.close()
        self.__cleanup()

    def execute(self, context: LaunchContext) -> List[LaunchDescriptionEntity] | None:
        """
        Executes the action, extending `ExecuteProcess` by handling events
        emitted from the child.
        """
        name = self.__process_description.final_name

        if self.__executed:
            raise RuntimeError(
                f"ExecuteLocal action '{name}': executed more than once: {self.describe()}"
            )

        if context.is_shutdown:
            # If shutdown starts before execution can start, don't start execution.
            return None

        # Register additional event handler for the extra communication
        context.register_event_handler(self.__extra_handler)

        try:
            return super().execute(context)
        except Exception:
            context.unregister_event_handler(self.__extra_handler)
            raise
