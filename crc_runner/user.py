#!/usr/bin/python
import asyncio
import asyncio.subprocess as aproc
import logging
import sys
from asyncio import CancelledError, StreamReader
from signal import SIGTERM
from typing import cast


from crc_runner import crc
from crc_runner.async_helpers import (
    CancelledFromInside,
    CancelledFromOutside,
    SignalError,
    check_signal,
    distinguish_cancellation,
)
from crc_runner.crc import SpawningStop, Stopping
from crc_runner.systemd import Notify

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


class UserCrcRunner:
    "Starts and monitors CRC, reacting to a stop request by shutting it down."

    def __init__(self):
        self.monitor = crc.CrcMonitor(POLL_INTERVAL_SECONDS)
        self.stop_state: SpawningStop | Stopping | None = None
        self.stop_task: asyncio.Task | None = None
        self.start_proc: aproc.Process = None  # type: ignore
        self.start_task = asyncio.create_task(self._crc_start())

    async def _line_reader(self, stderr: StreamReader, suppress: bool):
        while line := (await stderr.readline()).decode():
            print(line)
            if MismatchedBundleError.ERROR_MESSAGE_SUBSTRING in line and not suppress:
                raise MismatchedBundleError

    async def _crc_start(self):
        self.start_proc = proc = await crc.start()
        stderr = cast(StreamReader, proc.stderr)
        try:
            await self._line_reader(stderr, suppress=False)
            returncode = await proc.wait()
            if returncode != 0:
                log.error("`crc start` had exit status %s", returncode)
                # apparently it can exit with a failure but still have started
                # raise subprocess.CalledProcessError(returncode, "crc start", output)
        except MismatchedBundleError:
            proc.terminate()
            # continue to drain and print until exited
            _task = asyncio.create_task(self._line_reader(stderr, suppress=True))
            raise MismatchedBundleError(_task)

    async def stop(self, source: str):
        if self.stop_task is None:
            self.stop_task = asyncio.create_task(self._stop(source))
        else:
            log.info("Asked to stop from %s but already stopping", source)

        return await self.stop_task

    async def _stop(self, source: str):
        log.info(f"Stopping from {source}")
        while True:
            match self.stop_state:
                case None:
                    self.stop_state = SpawningStop(asyncio.create_task(crc.stop()))
                    # here just in case it throws, so the stop task can still start
                    Notify.stopping()

                    log.info("Cancelling start task")
                    self.start_task.cancel(msg="Stopping start_task from stop()")

                case SpawningStop(spawn_task):
                    proc = await spawn_task
                    # see if this was already set while awaiting (from another call)
                    if not isinstance(self.stop_state, Stopping):
                        self.stop_state = Stopping(asyncio.create_task(proc.wait()))

                case Stopping(stop_task):
                    log.info("Waiting on stop command")
                    await stop_task
                    return

    async def start(self):
        try:
            # wait for start
            await distinguish_cancellation(check_signal(self.start_task, SIGTERM))
        except MismatchedBundleError as e:
            Notify.notify("Bundle version mismatch")
            # TODO: this is all messy, spoopy action at a distance
            lines = cast(asyncio.Task, e.line_task)
            await lines
            retcode = await self.start_proc.wait()
            sys.exit(retcode)
        except CancelledFromOutside:
            log.info("start was cancelled, when would this happen though?")
            raise CancelledError
        except CancelledFromInside:
            # this also wouldn't happen, right? now that dbus is gone?
            log.info("start_exec was cancelled, must be from stopping")
            await self.stop_task  # type: ignore # TODO: can we make some guarantees here?
            raise CancelledError
        except CancelledError as e:
            log.info("Cancelled, stopping")
            await self.stop(STOPPING_FROM_CANCELLATION)
            raise
        except SignalError as e:
            log.info("Got SIGTERM, stopping CRC")
            await self.stop(STOPPING_FROM_SIGNAL)
            sys.exit()

        try:
            # wait for successful status
            log.info("Waiting for CRC to successfuly start")
            await check_signal(self.monitor.ready.wait(), SIGTERM)
            Notify.ready("CRC Started")
        except SignalError as e:
            log.info("Got SIGTERM, stopping CRC")
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
    print("Starting CRC instance")
    runner = UserCrcRunner()
    await runner.start()
    await runner.wait_until_stopped()