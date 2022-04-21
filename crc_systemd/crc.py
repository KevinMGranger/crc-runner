import asyncio
import asyncio.subprocess
import datetime
import enum
import json
import pathlib
import syslog

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


class StatusOutput:
    success: bool
    crc_status: CrcStatus
    openshift_status: OpenShiftStatus

    __match_args__ = ("success", "crc_status", "openshift_status")

    def __init__(self, success: bool, crcStatus: str, openshiftStatus: str, **_kwargs):
        self.success = success
        self.crc_status = CrcStatus(crcStatus)
        self.openshift_status = OpenShiftStatus(openshiftStatus)

    def __str__(self) -> str:
        return f"success={self.success} crc={self.crc_status.value} openshift={self.openshift_status.value}"

    @property
    def ready(self) -> bool:
        match (self.crc_status, self.openshift_status):
            case (CrcStatus.running, OpenShiftStatus.running):
                return True
            case _:
                return False

    @property
    def notify_status(self) -> str:
        return f"CRC is {self.crc_status.value}, OpenShift is {self.openshift_status.value}"


async def start() -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(CRC_PATH, *CRC_START_ARGS)


async def status() -> StatusOutput:
    status_proc = await asyncio.create_subprocess_exec(
        CRC_PATH, *CRC_STATUS_ARGS, stdout=asyncio.subprocess.PIPE
    )
    stdout_bytes = await status_proc.stdout.read()  # type: ignore
    return StatusOutput(**json.loads(stdout_bytes))


async def stop() -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(CRC_PATH, *CRC_STOP_ARGS)


async def monitor(interval: float):
    while True:
        journal.send("Running crc status check", PRIORITY=syslog.LOG_DEBUG)
        _status = await status()
        print(datetime.datetime.now(), _status)
        if _status.crc_status == CrcStatus.stopped:
            return
        elif _status.openshift_status == OpenShiftStatus.stopped:
            return
        else:
            journal.send(
                "Sleeping status check for interval", PRIORITY=syslog.LOG_DEBUG
            )
            await asyncio.sleep(interval)
