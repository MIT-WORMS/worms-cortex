from typing import Dict, Any, Iterable

import os
import struct
import asyncio
import socket
import traceback
from contextlib import suppress
from logging import Logger

from osrf_pycommon.process_utils import async_execute_process

from launch import LaunchContext, Event
from launch.actions import ExecuteProcess, ExecuteLocal
from launch.events.process import ProcessStarted, ProcessExited, ShutdownProcess
from launch.events import matches_action
from launch.conditions import evaluate_condition_expression
from launch.utilities import normalize_to_list_of_substitutions

from ..event_handlers import OnProcessPayload
from ..events.serialize import EventStream

SOCKET_ENVIRON = "_SOCKET_FD"
"""
Environment variable name set in the child process. Use 
`os.environ[SOCKET_ENVIRON]` to retrieve the file descriptor.
"""


class ExecutePipedProcess(ExecuteProcess):
    """
    Action that executes a process and sets up a communication pipe with it. The child
    process can then emit events in the parent process through this pipe. These events
    can be handled by registering appropriate event handlers.
    """

    def __init__(
        self, *, payload_handlers: Iterable[OnProcessPayload] | None = None, **kwargs
    ):
        """
        Constructs an `ExecutePipedProcess` action. Refer to `ExecuteProcess` for
        description of kwargs.

        Args:
            payload_handlers: An optional iterable of `OnProcessPayload` event handlers
        """
        self.__send_queue = None
        self.__payload_handlers = [] if payload_handlers is None else payload_handlers
        if payload_handlers is not None:
            self.__send_queue = asyncio.Queue()
            for handler in self.__payload_handlers:
                if not isinstance(handler, OnProcessPayload):
                    raise ValueError(
                        f"Invalid payload_handler type of {type(handler).__name__}"
                    )

                # Store a reference to the event queue in each handler
                handler.store_queue(self.__send_queue)

        super().__init__(**kwargs)

    __MANGLE_PREFIX = "_ExecuteLocal"
    __BaseProtocol = getattr(ExecuteLocal, f"{__MANGLE_PREFIX}__ProcessProtocol")

    class __PipedProcessProtocol(__BaseProtocol):
        """Subclassed to include an additional communication socket."""

        __MANGLE_PREFIX = "_ProcessProtocol"

        def __init__(
            self,
            action: ExecuteLocal,
            context: LaunchContext,
            process_event_args: Dict,
            reader: asyncio.StreamReader,
            **kwargs,
        ):
            super().__init__(action, context, process_event_args, **kwargs)
            self.__action = action
            self.__reader = reader
            self.__event_stream = EventStream()
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

            super().connection_lost(exc)

        def on_additional_socket_received(self, event: Event) -> None:
            """Custom logic for handling additional data from the process."""

            # Emit the event if no issues occurred
            self.__context.emit_event_sync(event)

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
            # Read data until StreamReader is closed
            while not self.__reader.at_eof():
                chunk = await self.__reader.read(1024)
                if not chunk:
                    break

                # Try to read the chunk, handle errors
                try:
                    events = self.__event_stream.read(chunk)

                    for event in events:
                        self.on_additional_socket_received(event)

                # Malformed header is fatal, terminate process
                except struct.error:
                    self.__logger.error(
                        "Invalid payload length in piped process.",
                        exc_info=True,
                    )
                    await self.__context.emit_event(
                        ShutdownProcess(process_matcher=matches_action(self.__action))
                    )
                    return

                # Log errors on invalid payloads
                except ValueError:
                    self.__logger.error(
                        "Failed to deserialize event from child process "
                        f"{self.__process_event_args['name']}; "
                        f"PID={self.__process_event_args['pid']}",
                        exc_info=True,
                    )
                except TypeError:
                    self.__logger.error(
                        f"Received non-Event payload "
                        f"from child process {self.__process_event_args['name']}; "
                        f"PID={self.__process_event_args['pid']}",
                    )

        """
        Properties to bypass name mangling
        """

        @property
        def __logger(self) -> Logger:
            return getattr(self, f"{self.__MANGLE_PREFIX}__logger")

        @property
        def __process_event_args(self) -> dict[str, Any]:
            return getattr(self, f"{self.__MANGLE_PREFIX}__process_event_args")

        @property
        def __context(self) -> LaunchContext:
            return getattr(self, f"{self.__MANGLE_PREFIX}__context")

    async def __event_writer_process(self, writer: asyncio.StreamWriter) -> None:
        if self.__send_queue is None:
            return
        try:
            while True:
                # Get next serialized event in queue
                raw = await self.__send_queue.get()
                self.__send_queue.task_done()

                # Log and pass invalid events
                if not isinstance(raw, bytes):
                    self.__logger.error("Invalid piped return type from server")
                    continue

                # Write event to child process
                writer.write(raw)
                await writer.drain()
        except asyncio.CancelledError:
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    async def _ExecuteLocal__execute_process(self, context: LaunchContext) -> None:
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
        fd_dict = {SOCKET_ENVIRON: str(subprocess_sock.fileno())}
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
                lambda **kwargs: self.__PipedProcessProtocol(
                    self, context, process_event_args, reader, **kwargs
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
                context.asyncio_loop.create_task(  # type: ignore
                    self._ExecuteLocal__execute_process(context)
                )
                if self.__send_queue is not None:
                    context.asyncio_loop.create_task(  # type: ignore
                        self.__event_writer_process(writer)
                    )
                return
        server_sock.close()
        subprocess_sock.close()
        self.__cleanup()

    def execute(self, context: LaunchContext) -> None:
        super().execute(context)
        if not context.is_shutdown:
            for handler in self.__payload_handlers:
                context.register_event_handler(handler)
        return None

    """
    Properties to bypass name mangling
    """

    def __cleanup(self) -> None:
        getattr(self, f"{self.__MANGLE_PREFIX}__cleanup")()

    @property
    def __process_event_args(self) -> dict[str, Any] | None:
        return getattr(self, f"{self.__MANGLE_PREFIX}__process_event_args")

    @property
    def __log_cmd(self) -> bool:
        return getattr(self, f"{self.__MANGLE_PREFIX}__log_cmd")

    @property
    def __logger(self) -> Logger:
        return getattr(self, f"{self.__MANGLE_PREFIX}__logger")

    @property
    def __emulate_tty(self) -> bool:
        return getattr(self, f"{self.__MANGLE_PREFIX}__emulate_tty")

    @property
    def __shell(self) -> bool:
        return getattr(self, f"{self.__MANGLE_PREFIX}__shell")

    @property
    def __shutdown_future(self) -> asyncio.Future | None:
        return getattr(self, f"{self.__MANGLE_PREFIX}__shutdown_future")

    @property
    def __respawn(self) -> bool:
        return getattr(self, f"{self.__MANGLE_PREFIX}__respawn")

    @property
    def __respawn_max_retries(self) -> int:
        return getattr(self, f"{self.__MANGLE_PREFIX}__respawn_max_retries")

    @property
    def __respawn_retries(self) -> int:
        return getattr(self, f"{self.__MANGLE_PREFIX}__respawn_retries")

    @__respawn_retries.setter
    def __respawn_retries(self, val) -> None:
        setattr(self, f"{self.__MANGLE_PREFIX}__respawn_retries", val)

    @property
    def __respawn_delay(self) -> float | None:
        return getattr(self, f"{self.__MANGLE_PREFIX}__respawn_delay")
