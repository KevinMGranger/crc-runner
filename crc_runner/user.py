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

# TODO: cancellation is a mistake.
# Events or something else to be awaited upon concurrently is how we do it.
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
    "A stop was requested on d bus."

    def __init__(self, task: asyncio.Task):
        self.task = tas 


class UserCrcRunner(ServiceInterface):
    "Starts and monitors CRC, reacting to a stop request by shutting it down."

    def __init__(self):
        self.monitor = crc.CrcMonitor(POLL_INTERVAL_SECONDS)
        self._drain_tasks: list[asyncio.Task] = []
        self.start_task: asyncio.Task[int] | None = None
        self.stop_task: asyncio.Task[int] | None = None
        self.stop_signal = asyncio.Event()

    async def _crc_start(self) -> int:
        """
        Run `crc start`.  Will terminate the crc start process if cancelled.
        Note that `crc start` returning successfully doesn't mean the cluster is ready yet.
        Even more confusingly, `crc start` returning non-zero doesn't mean it failed to start!
        """
        start_proc = await crc.start()
        stderr = cast(StreamReader, start_proc.stderr)
        start_log = log.getChild("crc start")

        log_lines_task = mktask(checking_log(stderr, MismatchedBundleError, start_log))

        try:
            await log_lines_task
            retcode = await start_proc.wait()
        except MismatchedBundleError:
            # Won't have successfully stopped the cluster, so we don't try to stop it here.
            msg = "Bundle mismatch. Manually delete cluster and run again."
            Notify.stopping(msg)
            log.error(msg)

            retcode = await start_proc.wait()
            log.error("`crc start` had exit status %s", retcode)
            sys.exit(retcode)
        except CancelledError:
            log.warning("startup cancelled, trying to terminate start task")
            # Drain lines while also shutting down.
            lines_task = asyncio.create_task(
                future_coro(asyncio.shield(non_checking_log(stderr, start_log)))
            )
            self._drain_tasks.append(lines_task)
            await asyncio.sleep(0)
            start_proc.terminate()
            raise

        # apparently it can exit with a failure but still have started,
        # so we don't exit our program here
        _log = log.error if retcode != 0 else log.info
        _log("`crc start` had exit status %s", retcode)
        return retcode

    async def _crc_stop(self) -> int:
        """
        Run `crc stop`.
        If the log line about not gracefully shutting down occurs,
        it will try doing `crc stop -f` as well.
        """
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

    @method(name="terminage")
    async def dbus_terminate(self) -> "i":  # type: ignore
        return await self.terminate()

    async def terminate(self) -> int:
        """
        Stop the cluster and exit.
        If it is currently in the process of starting,
        it will cancel that and start the exit process.
        """
        if self.start_task is not None:
            self.start_task.cancel()
        # _start() will call stop() too when cancelled,
        # but:
        # 1. that's good, internally consistent behavior
        # 2. we need to wait on stopping here
        # 3. calling stop() is idempotent anyway

        # maybe we shouldn't make it do that though?
        return await self.stop()

    async def stop(self) -> int:
        """
        "Latch" stop the cluster. That is, if the cluster
        is already stopping, wait on that.
        """
        if self.stop_task is None:
            self.stop_task = mktask(self._crc_stop())
            log.info("Waiting on stop")

        return await self.stop_task

    async def start(self):
        """
        "Latch" start the cluster. That is, if the cluster
        is already in the process of starting, wait on it.
        If it has already started, return the success or failure of that.
        """
        if self.start_task is None:
            self.start_task = mktask(self._start())

        return await self.start_task

    async def _start(self) -> int:
        """
        Start the cluster.

        Runs the start command and then waits for `crc status`
        to report that everything is successfully started.

        Will try to stop the cluster if cancelled, because
        cancelling `crc start` is not a guarantee that it's stopped.
        """
        try:
            # wait for start
            retcode = await self._crc_start()
            log.info("Waiting for CRC to successfuly start")
            await self.monitor.ready.wait()
            Notify.ready("CRC Started")
        except CancelledError:
            log.info("Startup cancelled, attempting to stop cluster")
            await self.stop()
            raise

        return retcode

    async def wait_until_stopped(self):
        # TODO: should report failure if it exits unexpectedly, right?
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

    # TODO: how to distinguish between regular stop and cancelled stop?
    # I really hope it's not switching away from CancelledError again 🤦
    try:
        try:
            await runner.start()
        except CancelledError:
            pass  # TODO

        try:
            await runner.wait_until_stopped()
        except CancelledError:
            pass  # TODO
    finally:
        await runner.wait_for_drains()
        bus.disconnect()
        await bus.wait_for_disconnect()
