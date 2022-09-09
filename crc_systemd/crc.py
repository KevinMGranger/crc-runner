import asyncio
import asyncio.subprocess
import datetime
import enum
import json
import pathlib
import syslog
from typing import AsyncIterable, AsyncIterator

from systemd import journal

CRC_PATH = pathlib.Path.home() / ".crc/bin/crc"
CRC_START_ARGS = ["start"]
CRC_STATUS_ARGS = ["status", "-o", "json"]
CRC_STOP_ARGS = ["stop"]

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


class StatusOutput:
    success: bool
    crc_status: CrcStatus
    openshift_status: OpenShiftStatus
    timestamp: datetime.datetime

    __match_args__ = ("success", "crc_status", "openshift_status")

    def __init__(self, success: bool, crcStatus: str, openshiftStatus: str, timestamp: datetime.datetime, **_kwargs):
        self.success = success
        self.crc_status = CrcStatus(crcStatus)
        self.openshift_status = OpenShiftStatus(openshiftStatus)
        self.timestamp = timestamp

    def __str__(self) -> str:
        return f"success={self.success} crc={self.crc_status.value} openshift={self.openshift_status.value}"

    @property
    def ready(self) -> bool:
        return (self.crc_status, self.openshift_status) == (CrcStatus.running, OpenShiftStatus.running)

    @property
    def notify_status(self) -> str:
        return f"CRC is {self.crc_status.value}, OpenShift is {self.openshift_status.value}"


class CrcMonitor:
    # interval: float
    # last_status: StatusOutput | None
    # monitor_task: asyncio.Task[None]

    def __init__(self, interval: float):
        self.interval = interval
        self.last_status : StatusOutput | None = None
        self.monitor_task = asyncio.create_task(self._monitor())
        self.ready = asyncio.Event()

    # todo: wait did this even need to be cancellable?
    def cancel(self, msg=None):
        self.monitor_task.cancel(msg)

    async def _monitor(self):
        while True:
            journal.send("Running crc status check", PRIORITY=syslog.LOG_DEBUG)
            self.last_status = await status()
            print(datetime.datetime.now(), self.last_status)
            if self.last_status.ready:
                self.ready.set() # go
            await asyncio.sleep(self.interval)

async def monitor_generator() -> AsyncIterator[StatusOutput]:
    while True:
        yield await status()

async def start() -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(CRC_PATH, *CRC_START_ARGS)


async def status() -> StatusOutput:
    status_proc = await asyncio.create_subprocess_exec(
        CRC_PATH, *CRC_STATUS_ARGS, stdout=asyncio.subprocess.PIPE
    )
    stdout_bytes = await status_proc.stdout.read()  # type: ignore
    return StatusOutput(**json.loads(stdout_bytes), timestamp=datetime.datetime.now())


async def stop() -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(CRC_PATH, *CRC_STOP_ARGS)
