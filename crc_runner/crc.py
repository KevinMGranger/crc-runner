from __future__ import annotations

import asyncio
import asyncio.subprocess
import enum
import json
import logging
import pathlib
from dataclasses import dataclass
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

CRC_PATH = pathlib.Path.home() / ".crc/bin/crc"
CRC_START_ARGS = ["start"]
CRC_STATUS_ARGS = ["status", "-o", "json"]
CRC_STOP_ARGS = ["stop"]

OTHER_ERROR_START = "Cannot get machine state"

# TODO: polling status may not be necessary?
# seemed to not be while testing but I swear I've seen relying on crc start not be enough.


class CrcStatus(enum.Enum):
    stopped = "Stopped"
    running = "Running"


class OpenShiftStatus(enum.Enum):
    running = "Running"
    unreachable = "Unreachable"
    stopped = "Stopped"
    starting = "Starting"
    degraded = "Degraded"

    @property
    def is_bad(self):
        return self in (OpenShiftStatus.unreachable, OpenShiftStatus.degraded)


class NotYetExtant:
    MESSAGE = "Machine does not exist. Use 'crc start' to create it"

    @staticmethod
    def __str__():
        return NotYetExtant.MESSAGE


class OtherError:
    def __init__(self, error: str):
        self.error = error

    def __str__(self):
        return self.error


class StatusOutput:
    __match_args__ = ("crc_status", "openshift_status")

    def __init__(
        self,
        crcStatus: str,
        openshiftStatus: str,
        **_kwargs,
    ):
        self.crc_status = CrcStatus(crcStatus)
        self.openshift_status = OpenShiftStatus(openshiftStatus)

    def __str__(self) -> str:
        return f"crc={self.crc_status.value} openshift={self.openshift_status.value}"

    @property
    def notify_status(self) -> str:
        return f"CRC is {self.crc_status.value}, OpenShift is {self.openshift_status.value}"


class LifeCycleState(enum.Enum):
    not_yet_started = enum.auto()
    starting = enum.auto()
    running = enum.auto()
    stopped = enum.auto()


class StatusTracker:
    def __init__(self, status: OpenShiftStatus):
        self.status = status
        self.latest_time = self.earliest_time = datetime.now()

    def update(self, status: OpenShiftStatus):
        if status == self.status:
            self.latest_time = datetime.now()
        else:
            self.status = status
            self.latest_time = self.earliest_time = datetime.now()

    @property
    def duration(self) -> timedelta:
        return self.latest_time - self.earliest_time


class CrcMonitor:
    def __init__(self, interval: float):
        self.interval = interval
        self.tracked_status: StatusTracker | None = None
        "Time-tracked OpenShift status"
        self.lifecycle = LifeCycleState.not_yet_started
        log.debug("Creating monitor")
        self.monitor_task = asyncio.create_task(self._monitor())
        self.ready = asyncio.Event()
        self.stopped = asyncio.Event()

    def update_status(self, status: OpenShiftStatus):
        if self.tracked_status is None:
            self.tracked_status = StatusTracker(status)
        else:
            self.tracked_status.update(status)

            if status.is_bad and (duration := self.tracked_status.duration):
                log.warning(
                    "OpenShift has been %s for %s", status.value.lower(), duration
                )

    # todo: wait did this even need to be cancellable?
    def cancel(self, msg=None):
        self.monitor_task.cancel(msg)

    async def _check_single_status(self):
        log.debug("Running crc status check")
        self.last_status = await status()
        log.info("Got lifecycle %s, status %s", self.lifecycle, self.last_status)
        if not isinstance(self.last_status, StatusOutput):
            return

        os_status = self.last_status.openshift_status
        self.update_status(os_status)

        match (self.lifecycle, os_status):
            case LifeCycleState.not_yet_started, OpenShiftStatus.stopped:
                pass
            case LifeCycleState.not_yet_started | LifeCycleState.starting, OpenShiftStatus.starting:
                self.lifecycle = LifeCycleState.starting
            case LifeCycleState.not_yet_started, OpenShiftStatus.unreachable if self.last_status.crc_status is CrcStatus.running:
                self.lifecycle = LifeCycleState.starting
            case _, OpenShiftStatus.running:
                self.lifecycle = LifeCycleState.running
                self.ready.set()  # go
            case LifeCycleState.starting, OpenShiftStatus.unreachable | OpenShiftStatus.degraded | OpenShiftStatus.stopped:
                pass
            case LifeCycleState.running, _:
                if self.last_status.crc_status is CrcStatus.stopped:
                    self.lifecycle = LifeCycleState.stopped
                    self.stopped.set()
            case _:
                log.error(
                    "Unconsidered or illegal lifecycle-status combo %s %s",
                    self.lifecycle,
                    os_status,
                )

    async def _monitor(self):
        log.debug("Starting monitor loop")
        while True:
            await self._check_single_status()
            await asyncio.sleep(self.interval)


async def start() -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        CRC_PATH,
        *CRC_START_ARGS,
        stderr=asyncio.subprocess.PIPE,
    )


async def status() -> StatusOutput | NotYetExtant | OtherError:
    status_proc = await asyncio.create_subprocess_exec(
        CRC_PATH, *CRC_STATUS_ARGS, stdout=asyncio.subprocess.PIPE
    )
    stdout_bytes = await status_proc.stdout.read()  # type: ignore
    output = json.loads(stdout_bytes)

    match output:
        case {
            "success": False,
            "error": str() as error,
        } if error == NotYetExtant.MESSAGE:
            return NotYetExtant()
        case {"success": False, "error": str() as error}:
            return OtherError(error)
        case {"success": True}:
            return StatusOutput(**output)
        case _:
            raise Exception(f"Unknown output status: {output}")


async def stop() -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(CRC_PATH, *CRC_STOP_ARGS)


@dataclass(frozen=True)
class SpawningStop:
    task: asyncio.Task[asyncio.subprocess.Process]


@dataclass(frozen=True)
class Stopping:
    task: asyncio.Task[int]
