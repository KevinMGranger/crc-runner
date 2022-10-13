#!/usr/bin/python
import asyncio
import asyncio.subprocess as aproc
import logging
import sys
from asyncio import CancelledError, StreamReader
from signal import SIGTERM
from typing import NamedTuple, cast

from crc_runner import crc
from crc_runner._systemd import Notify
from crc_runner.async_helpers import (
    SignalError,
    check_signal,
)
from crc_runner.crc import SpawningStop, Stopping

POLL_INTERVAL_SECONDS = 6

log = logging.getLogger(__name__)

CANCELLED_FROM_STOP_CALL = "cancelled from dbus stop"
CANCELLED_FROM_SIGNAL = "cancelled from signal"

# TODO: after removing dbus, do we need these different reasons? when would the user runner even be cancelled?
STOPPING_FROM_DBUS = "dbus"
STOPPING_FROM_SIGNAL = "SIGTERM"
STOPPING_FROM_CANCELLATION = "cancellation"


class MismatchedBundleError(Exception):
    ERROR_MESSAGE_SUBSTRING = "was requested, but the existing VM is using"

    def __init__(self, line_task: asyncio.Task | None = None):
        super().__init__()
        self.line_task = line_task


class StartupProcess(NamedTuple):
    process: aproc.Process
    task: asyncio.Task


class UserCrcRunner:
    "Starts and monitors CRC, reacting to a stop request by shutting it down."

    def __init__(self):
        self.monitor = crc.CrcMonitor(POLL_INTERVAL_SECONDS)
        self.stop_state: SpawningStop | Stopping | None = None
        self.stop_task: asyncio.Task | None = None
        self.startup: StartupProcess | None = None

    async def _line_reader(self, stderr: StreamReader, suppress: bool):
        while line := (await stderr.readline()).decode():
            log.info(line)
            if MismatchedBundleError.ERROR_MESSAGE_SUBSTRING in line and not suppress:
                raise MismatchedBundleError

    async def _crc_start(self, proc: aproc.Process):
        stderr = cast(StreamReader, proc.stderr)
        try:
            await self._line_reader(stderr, suppress=False)
            returncode = await proc.wait()
            if returncode != 0:
                log.error("`crc start` had exit status %s", returncode)
                # apparently it can exit with a failure but still have started
                # raise subprocess.CalledProcessError(returncode, "crc start", output)
            self.startup = None
        except MismatchedBundleError:
            proc.terminate()
            # continue to drain and print until exited
            # TODO: could this just be piped / spliced?
            _task = asyncio.create_task(
                self._line_reader(stderr, suppress=True),
                name="User _crc_start bundle error line reader",
            )
            raise MismatchedBundleError(_task)

    async def stop(self, source: str):
        if self.stop_task is None:
            self.stop_task = asyncio.create_task(
                self._stop(source), name="User stop stop_task"
            )
        else:
            log.info("Asked to stop from %s but already stopping", source)

        return await self.stop_task

    async def _stop(self, source: str):
        log.info(f"Stopping from {source}")
        while True:
            match self.stop_state:
                case None:
                    self.stop_state = SpawningStop(
                        asyncio.create_task(crc.stop(), name="User._stop crc stop")
                    )
                    # here just in case it throws, so the stop task can still start
                    Notify.stopping()

                    log.info("Cancelling start task")
                    if self.startup is not None:
                        # TODO: does it go back and forth? no, but only because of the stop facade.
                        # Still messy.
                        self.startup.process.terminate()  # TODO: should start handle this when cancelled?
                        self.startup.task.cancel(msg="Stopping start_task from stop()")

                case SpawningStop(spawn_task):
                    proc = await spawn_task
                    # see if this was already set while awaiting (from another call)
                    if not isinstance(self.stop_state, Stopping):
                        self.stop_state = Stopping(
                            asyncio.create_task(
                                proc.wait(), name="User._stop crc stop wait"
                            )
                        )

                case Stopping(stop_task):
                    log.info("Waiting on stop command")
                    await stop_task
                    return

    async def start(self):
        if self.startup is None:
            proc = await crc.start()
            self.startup = StartupProcess(
                proc, asyncio.create_task(self._start(proc), name="User start _start")
            )
        await self.startup.task

    async def _start(self, proc: aproc.Process):
        try:
            # wait for start
            await check_signal(self._crc_start(proc), SIGTERM)
        except MismatchedBundleError as e:
            # no need to stop since it will fail to start
            Notify.notify("Bundle version mismatch")
            # TODO: this is all messy, spoopy action at a distance
            lines = cast(asyncio.Task, e.line_task)
            await lines
            startup = cast(StartupProcess, self.startup)
            retcode = await startup.process.wait()
            sys.exit(retcode)
        except CancelledError as e:
            log.info("Cancelled, stopping")
            # if this did actually cancel "itself", would it stop progressing if it wasn't a task?
            await self.stop(STOPPING_FROM_CANCELLATION)
            raise
        except SignalError as e:
            log.info("Got SIGTERM, stopping CRC")
            await self.stop(STOPPING_FROM_SIGNAL)
            sys.exit()
        except Exception:
            log.error("unknown exception, stopping CRC")
            await self.stop("unknown")
            raise

        try:
            # wait for successful status
            log.info("Waiting for CRC to successfuly start")
            # TODO: do we need an abstraction for cancelling when a signal is received? or do we just need to always do it ourselves?
            await check_signal(self.monitor.ready.wait(), SIGTERM)
            Notify.ready("CRC Started")
        except SignalError as e:
            log.info("Got SIGTERM, stopping CRC")
            e.task.cancel()
            await self.stop(STOPPING_FROM_SIGNAL)
            sys.exit()

    async def wait_until_stopped(self):
        try:
            await check_signal(self.monitor.stopped.wait(), SIGTERM)
        except SignalError as e:
            log.info("Got SIGTERM, stopping CRC")
            await self.stop(STOPPING_FROM_SIGNAL)
            await self.monitor.stopped.wait()
            sys.exit()


async def run():
    log.info("Starting CRC instance")
    runner = UserCrcRunner()
    await runner.start()
    await runner.wait_until_stopped()
