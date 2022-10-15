#!/usr/bin/python
from __future__ import annotations
import asyncio
from dbus_next.aio import MessageBus, ProxyObject
from dbus_next.service import ServiceInterface, method
import asyncio.subprocess as aproc
from dataclasses import dataclass
import logging
import sys
from asyncio import (
    CancelledError,
    InvalidStateError,
    StreamReader,
    create_task as mktask,
)
from signal import SIGTERM
from typing import ClassVar, NamedTuple, TypeVar, cast
import typing
from crc_runner import dbus

from crc_runner import crc
from crc_runner._systemd import Notify
from crc_runner.async_helpers import (
    SignalError,
    check_event,
    check_signal,
    future_coro,
)

POLL_INTERVAL_SECONDS = 6

log = logging.getLogger(__name__)

T = TypeVar("T")

# TODO: signal handling sucks and was a mistake. Let's go back to dbus.

# handling these lines properly if they don't close is hard. I guess they'd get epipe.
# but maybe I just don't use JournalHandler and instead run subprograms through
class ErrorMessageLineError(Exception):
    ERROR_MESSAGE_SUBSTRING: ClassVar[str]


Exc = TypeVar("Exc", bound=ErrorMessageLineError)


async def checking_log(stream: StreamReader, exc: type[Exc], log: logging.Logger):
    while line := (await stream.readline()).decode():
        if exc.ERROR_MESSAGE_SUBSTRING in line:
            log.error(line)
            raise exc()
        log.info(line)


async def non_checking_log(stream: StreamReader, log: logging.Logger):
    said_drained = False
    while line := (await stream.readline()).decode():
        # temporary
        if not said_drained:
            log.debug("drain gang")
            said_drained = True
        log.info(line)


class MismatchedBundleError(ErrorMessageLineError):
    ERROR_MESSAGE_SUBSTRING = "was requested, but the existing VM is using"


class CannotGracefullyShutdownError(ErrorMessageLineError):
    ERROR_MESSAGE_SUBSTRING = (
        "Cannot stop machine: VM Failed to gracefully shutdown, try the kill command"
    )


class StopRequested(Exception):
    def __init__(self, task: asyncio.Task):
        self.task = task


class UserCrcRunner(ServiceInterface):
    "Starts and monitors CRC, reacting to a stop request by shutting it down."

    def __init__(self):
        self.monitor = crc.CrcMonitor(POLL_INTERVAL_SECONDS)
        self._drain_tasks: list[asyncio.Task] = []
        self.stop_task: asyncio.Task | None = None
        self.stop_requested = asyncio.Event()

    async def check_for_stop(self, awaitable: typing.Awaitable[T]) -> T:
        return await check_event(awaitable, self.stop_requested, StopRequested)

    async def _crc_start(self) -> int:
        start_proc = await crc.start()
        stderr = cast(StreamReader, start_proc.stderr)
        start_log = log.getChild("crc start")

        try:
            await check_signal(
                checking_log(stderr, MismatchedBundleError, start_log), SIGTERM
            )
            retcode = await start_proc.wait()
        except MismatchedBundleError:
            msg = "Bundle mismatch. Manually delete cluster and run again."
            Notify.stopping(msg)
            log.error(msg)

            retcode = await start_proc.wait()
            log.error("`crc start` had exit status %s", retcode)
            sys.exit(retcode)
        except SignalError as e:
            log.info("Got SIGTERM, cancelling CRC start")
            e.task.cancel()  # existing line reader
            # Drain lines while also shutting down.
            lines_task = asyncio.create_task(
                future_coro(asyncio.shield(non_checking_log(stderr, start_log)))
            )
            self._drain_tasks.append(lines_task)
            await asyncio.sleep(0)
            raise

        # apparently it can exit with a failure but still have started,
        # so we don't exit our program here
        _log = log.error if retcode != 0 else log.info
        _log("`crc start` had exit status %s", retcode)
        return retcode

    async def _crc_stop(self) -> int:
        stop_proc = await crc.stop(force=False)
        stderr = cast(StreamReader, stop_proc.stderr)
        stop_log = log.getChild("crc stop")

        try:
            await checking_log(stderr, CannotGracefullyShutdownError, stop_log)
            return await stop_proc.wait()
        except CannotGracefullyShutdownError:
            lines_task = mktask(
                future_coro(asyncio.shield(non_checking_log(stderr, stop_log)))
            )
            self._drain_tasks.append(lines_task)

            Notify.notify("forcing stop")
            force_proc = await crc.stop(force=True)
            stderr = cast(StreamReader, force_proc.stderr)

            await non_checking_log(stderr, log.getChild("crc stop -f"))
            return await stop_proc.wait()

    @method(name="stop")
    async def dbus_stop(self) -> "i":  # type: ignore
        return await self.stop()

    async def stop(self):
        if self.stop_task is None:
            self.stop_task = mktask(self._crc_stop())
            log.info("Waiting on stop")

        return await self.stop_task

    async def start(self):
        try:
            # wait for start
            await self._crc_start()
        except SignalError as e:
            log.info("Got SIGTERM, stopping CRC")
            await self.stop()
            sys.exit(128 + SIGTERM)

        try:
            log.info("Waiting for CRC to successfuly start")
            await check_signal(self.monitor.ready.wait(), SIGTERM)
            Notify.ready("CRC Started")
        except SignalError as e:
            msg = "Got SIGTERM, stopping CRC"

            log.info(msg)
            Notify.stopping(msg)

            e.task.cancel()  # monitor wait

            await self.stop()
            sys.exit()

    async def wait_until_stopped(self):
        try:
            await check_signal(self.monitor.stopped.wait(), SIGTERM)
        except SignalError as e:
            log.info("Got SIGTERM, stopping CRC")
            await self.stop()
            await self.monitor.stopped.wait()

    async def wait_for_drains(self):
        await asyncio.wait(self._drain_tasks)


async def run():
    log.info("Connecting to dbus")
    bus = await dbus.connect()
    await bus.request_name("fyi.kmg.crc_runner")
    runner = UserCrcRunner()
    bus.export("/fyi/kmg/crc_runner/Runner1", runner)
    log.info("Starting CRC instance")
    await runner.start()
    await runner.wait_until_stopped()
    await runner.wait_for_drains()
    bus.disconnect()
    await bus.wait_for_disconnect()
