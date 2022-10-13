#!/usr/bin/python
import asyncio
import asyncio.subprocess as aproc
import logging
import sys
from asyncio import CancelledError, InvalidStateError, StreamReader
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


# class ErrorMessageLineError(Exception):
#     def __init__(self, line: str, task: asyncio.Task):
#         super().__init__(line)
#         self.line = line
#         self.task = task

ErrorMessageLineError = Exception


class MismatchedBundleError(ErrorMessageLineError):
    ERROR_MESSAGE_SUBSTRING = "was requested, but the existing VM is using"


class CannotGracefullyShutdownError(ErrorMessageLineError):
    ERROR_MESSAGE_SUBSTRING = (
        "Cannot stop machine: VM Failed to gracefully shutdown, try the kill command"
    )


class StartupProcess(NamedTuple):
    process: aproc.Process
    task: asyncio.Task


# UGH HOW DO I HANDLE ERRORS THAT BUBBLE UP WHILE STILL WANTING TO HANDLE LINES
# for now, let's just pretend it won't be an issue. Might not even need to wait for tasks to exit.
# just keeping this for reference.
# TODO: could this just be piped / spliced?
# async def just_forward_lines(stderr: StreamReader, log: logging.Logger):
#     said_drained_yet = False

#     while line := (await stderr.readline()).decode():
#         if not said_drained_yet:
#             log.debug("DRAINED LINE")
#             said_drained_yet = True
#         # TODO: why don't these double up on newlines?
#         log.info(line)


# TODO: pass logger from contextvar
async def _read_stop_lines(stderr: StreamReader, log: logging.Logger):
    while line := (await stderr.readline()).decode():
        # TODO: why don't these double up on newlines?
        if CannotGracefullyShutdownError.ERROR_MESSAGE_SUBSTRING in line:
            log.error(line)
            raise CannotGracefullyShutdownError

        log.info(line)


async def _start_line_reader(stderr: StreamReader, log: logging.Logger):
    while line := (await stderr.readline()).decode():
        if MismatchedBundleError.ERROR_MESSAGE_SUBSTRING in line:
            log.error(line)
            raise MismatchedBundleError

        log.info(line)


class UserCrcRunner:
    "Starts and monitors CRC, reacting to a stop request by shutting it down."

    def __init__(self):
        self.monitor = crc.CrcMonitor(POLL_INTERVAL_SECONDS)
        self.start_task: asyncio.Task | None = None
        self.stop_task: asyncio.Task | None = None

    async def _crc_start(self):
        # TODO: can we pipe these starts into some sort of journald-tee,
        # so we can react to them and also have them forwarded even if we exit?
        start_proc = await crc.start()
        stderr = cast(StreamReader, start_proc.stderr)

        try:
            await _start_line_reader(stderr, log.getChild("crc start"))
        except MismatchedBundleError:
            # TODO: shield from cancellation or do something else to make this still work
            log.error("Bundle mismatch. Manually delete cluster and run again.")
            # TODO: do we terminate the start proc? for now, no.

            retcode = await start_proc.wait()
            log.error("`crc start` had exit status %s", retcode)
            sys.exit(retcode)

        except CancelledError:
            # drain lines while also shutting down
            stop_task = asyncio.create_task(self.stop("crc start cancelled"))
            lines_task = asyncio.shield(
                just_forward_lines(stderr, log.getChild("crc start"))
            )
            await asyncio.wait((stop_task, lines_task))
            raise

        try:
            lines_task.result()
        except InvalidStateError:
            await lines_task

        retcode = await start_task

        if retcode != 0:
            log.error("`crc start` had exit status %s", retcode)
            # apparently it can exit with a failure but still have started,
            # so we don't exit our program here

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

        log.debug("Spawning stop process")
        stop_proc = await crc.stop()

        Notify.stopping()

        wait_task = asyncio.create_task(stop_proc.wait())
        stderr = cast(StreamReader, stop_proc.stderr)
        lines_task = asyncio.create_task(
            _read_stop_lines(stderr, log.getChild("crc stop"))
        )

        log.info("Waiting on stop")
        to_run = {wait_task, lines_task}
        await asyncio.wait(to_run, return_when=asyncio.FIRST_COMPLETED)

        to_run: set[asyncio.Task] = set()
        try:
            lines_task.result()
        except InvalidStateError:
            # not done yet
            pass
        except CannotGracefullyShutdownError:
            to_run.add(
                asyncio.create_task(
                    just_forward_lines(stderr, log.getChild("crc stop"))
                )
            )
            force_proc = await crc.stop(force=True)
            force_task = asyncio.create_task(force_proc.wait())
            force_lines_task = asyncio.create_task(
                just_forward_lines(
                    cast(StreamReader, force_proc.stderr), log.getChild("crc stop -f")
                )
            )
            to_run |= {force_task, force_lines_task}

        try:
            wait_task.result()
        except InvalidStateError:
            to_run.add(wait_task)

        # TODO: signal handling?
        await asyncio.wait(to_run, return_when=asyncio.ALL_COMPLETED)

    async def start(self):
        if self.start_task is None:
            self.start_task = asyncio.create_task(self._start())
        await self.startup.task

    async def _start(self, proc: aproc.Process):
        try:
            # wait for start
            await check_signal(self._crc_start(proc), SIGTERM)
        except MismatchedBundleError:
            # no need to stop since it will fail to start
            Notify.stopping("Bundle version mismatch")
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
