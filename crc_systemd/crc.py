from __future__ import annotations
import asyncio
import asyncio.subprocess
from dataclasses import dataclass
import datetime
import enum
import json
import pathlib
import logging

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


class NotYetExtant:
    MESSAGE = "Machine does not exist. Use 'crc start' to create it"
    ready = False

    def __init__(self, timestamp: datetime.datetime):
        self.timestamp = timestamp

    @staticmethod
    def __str__():
        return NotYetExtant.MESSAGE


class OtherError:
    ready = False

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
    def ready(self) -> bool:
        return (self.crc_status, self.openshift_status) == (
            CrcStatus.running,
            OpenShiftStatus.running,
        )

    @property
    def notify_status(self) -> str:
        return f"CRC is {self.crc_status.value}, OpenShift is {self.openshift_status.value}"


class LifeCycleState(enum.Enum):
    not_yet_started = enum.auto()
    starting = enum.auto()
    running = enum.auto()
    stopped = enum.auto()


class CrcMonitor:
    def __init__(self, interval: float):
        self.interval = interval
        self.last_status: StatusOutput | NotYetExtant | OtherError | None = None
        self.lifecycle = LifeCycleState.not_yet_started
        log.debug("Creating monitor")
        self.monitor_task = asyncio.create_task(self._monitor())
        self.ready = asyncio.Event()
        self.stopped = asyncio.Event()

    # todo: wait did this even need to be cancellable?
    def cancel(self, msg=None):
        self.monitor_task.cancel(msg)

    async def _check_single_status(self):
        log.debug("Running crc status check")
        self.last_status = await status()
        log.info(self.lifecycle, self.last_status)
        match (self.lifecycle, self.last_status):
            case _, StatusOutput() as last_status if last_status.ready:
                self.lifecycle = LifeCycleState.running
                self.ready.set()  # go
            case LifeCycleState.not_yet_started, StatusOutput(
                _, OpenShiftStatus.starting
            ):
                self.lifecycle = LifeCycleState.starting
            case LifeCycleState.running, StatusOutput(CrcStatus.stopped, _):
                self.lifecycle = LifeCycleState.stopped
                self.stopped.set()
            case _, OtherError() | NotYetExtant():
                # :(
                pass
            case _:
                log.error(
                    "Unconsidered or illegal lifecycle-status combo %s %s",
                    self.lifecycle,
                    self.last_status,
                )

    async def _monitor(self):
        log.debug("Starting monitor loop")
        while True:
            await self._check_single_status()
            await asyncio.sleep(self.interval)


async def start() -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        CRC_PATH, *CRC_START_ARGS, stdout=asyncio.subprocess.PIPE
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
            return NotYetExtant(datetime.datetime.now())
        case {"success": False, "error": str() as error}:
            return OtherError(error)
        case {"success": True}:
            return StatusOutput(**output, timestamp=datetime.datetime.now())
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
