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


class NotYetExtant:
    MESSAGE = "Machine does not exist. Use 'crc start' to create it"
    ready = False

    def __init__(self, timestamp: datetime.datetime):
        self.timestamp = timestamp

    @staticmethod
    def __str__():
        return NotYetExtant.MESSAGE


class StatusOutput:
    def __init__(
        self,
        crcStatus: str,
        openshiftStatus: str,
        timestamp: datetime.datetime,
        **_kwargs,
    ):
        self.crc_status = CrcStatus(crcStatus)
        self.openshift_status = OpenShiftStatus(openshiftStatus)
        self.timestamp = timestamp

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


class CrcMonitor:
    def __init__(self, interval: float):
        self.interval = interval
        self.last_status: StatusOutput | NotYetExtant | None = None
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
                self.ready.set()  # go
            await asyncio.sleep(self.interval)


async def monitor_generator() -> AsyncIterator[StatusOutput | NotYetExtant]:
    while True:
        yield await status()


async def start() -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(CRC_PATH, *CRC_START_ARGS)


async def status() -> StatusOutput | NotYetExtant:
    status_proc = await asyncio.create_subprocess_exec(
        CRC_PATH, *CRC_STATUS_ARGS, stdout=asyncio.subprocess.PIPE
    )
    stdout_bytes = await status_proc.stdout.read()  # type: ignore
    output = json.loads(stdout_bytes)
    if not output["success"] and output["error"] == NotYetExtant.MESSAGE:
        return NotYetExtant(datetime.datetime.now())
    return StatusOutput(**output, timestamp=datetime.datetime.now())


async def stop() -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(CRC_PATH, *CRC_STOP_ARGS)
