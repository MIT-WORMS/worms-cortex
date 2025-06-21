from typing import Dict

import os
import struct
import pickle
import asyncio
import socket
import traceback
from contextlib import suppress

from osrf_pycommon.process_utils import async_execute_process

from launch import LaunchContext, Event
from launch.actions import ExecuteProcess, ExecuteLocal
from launch.events.process import ProcessStarted, ProcessExited, ShutdownProcess
from launch.events import matches_action
from launch.conditions import evaluate_condition_expression
from launch.utilities import normalize_to_list_of_substitutions


class ExecutePipedProcess(ExecuteProcess):
    """
    Action that executes a process and sets up a communication pipe with it. The child
    process can then emit events in the parent process through this pipe. These events
    can be handled by registering an `OnPipedOutput` event handler.
    """

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
            self.__action = action
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
            try:
                # Try to deserialize the event object from the child
                event = pickle.loads(data)
                if not isinstance(event, Event):
                    self.__logger.error(
                        f"Received non-Event payload '{type(event).__name__}' "
                        f"from child process {self.__process_event_args['name']}; "
                        f"PID={self.__process_event_args['pid']}",
                    )
                    return

                # Emit the event if no issues occurred
                self.__context.emit_event_sync(event)

            except Exception:
                self.__logger.error(
                    "Failed to deserialize event from child process "
                    f"{self.__process_event_args['name']}; "
                    f"PID={self.__process_event_args['pid']}",
                    exc_info=True,
                )

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
            buffer = b""
            expected_length = None

            # Read data until StreamReader is closed
            while not self.__reader.at_eof():
                chunk = await self.__reader.read(1024)
                if not chunk:
                    break

                while True:
                    # Attempt to extract payload length
                    if expected_length is None:
                        # Not enough data for package length
                        if len(buffer) < 4:
                            break

                        # Unpack package length, error if malformed
                        try:
                            expected_length = struct.unpack(">I", buffer[:4])[0]
                            buffer = buffer[4:]
                        except struct.error:
                            self.__logger.error(
                                "Invalid payload length in piped process.",
                                exc_info=True,
                            )
                            await self.__context.emit_event(
                                ShutdownProcess(
                                    process_matcher=matches_action(self.__action)
                                )
                            )
                            return

                    # Not enough data for payload
                    if len(buffer) < expected_length:
                        break

                    # Unpack payload
                    payload = buffer[:expected_length]
                    buffer = buffer[expected_length:]
                    expected_length = None
                    self.on_additional_socket_received(payload)

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
