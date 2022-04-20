#!/usr/bin/python

import datetime
import enum
import json
import logging
import os.path
import subprocess
import sys
import time
import asyncio
import os

import systemd.daemon
from systemd import journal
from dbus_next.aio import MessageBus

POLL_INTERVAL_SECONDS = 6
LOG_INFO = 6
CRC_PATH = f"{os.path.expanduser('~')}/.crc/bin/crc"
CRC_START_ARGS = [CRC_PATH, "start"]
CRC_STATUS_ARGS = [CRC_PATH, "status", "-o", "json"]
CRC_STOP_ARGS = [CRC_PATH, "stop"]

SYSTEMD_OBJECT_PATH = "/org/freedesktop/systemd1"
SYSTEMD_MANAGER_IFACE = "org.freedesktop.systemd1.Manager"
SYSTEMD_BUS_NAME = "org.freedesktop.systemd1"
SYSTEMD_SERVICE_IFACE = "org.freedesktop.systemd1.Service"
SYSTEMD_UNIT_IFACE = "org.freedesktop.systemd1.Unit"


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


class UnitActiveState(enum.Enum):
    active = "active"
    reloading = "reloading"
    inactive = "inactive"
    failed = "failed"
    activating = "activating"
    deactivating = "deactivating"


def crc_start():
    subprocess.run(CRC_START_ARGS, check=True)


def crc_status() -> StatusOutput:
    logging.debug("Running %s", CRC_STATUS_ARGS)
    completed = subprocess.run(
        CRC_STATUS_ARGS, capture_output=True, check=True, text=True
    )
    return StatusOutput(**json.loads(completed.stdout))


def crc_stop():
    subprocess.run(CRC_STOP_ARGS, check=True)


def _notify(
    ready: bool | None = None,
    stopping: bool | None = None,
    status: str | None = None,
    **messages: str,
):
    if ready:
        messages["READY"] = "1"
    if stopping:
        messages["STOPPING"] = "1"

    if status:
        messages["STATUS"] = status

    msg = "\n".join((f"{kw}={val}" for kw, val in messages.items()))
    systemd.daemon.notify(msg)


def print_status(status: StatusOutput):
    print(f"CRC Status: {status}")


def start():
    _notify(status="Starting CRC instance")
    crc_start()
    # startup
    while True:
        status = crc_status()
        print_status(status)
        if status.ready:
            _notify(ready=True, status="CRC Started")
            break
        else:
            _notify(status=f"Waiting for reachability: {status.notify_status}")

    monitor()


def monitor():
    while True:
        status = crc_status()
        print_status(status)
        time.sleep(POLL_INTERVAL_SECONDS)


def watch_and_log_statuses():
    while True:
        status = crc_status()
        print(datetime.datetime.now(), status)
        time.sleep(POLL_INTERVAL_SECONDS)


async def make_proxy(bus, bus_name, path):
    return bus.get_proxy_object(bus_name, path, await bus.introspect(bus_name, path))


job_starts = []
job_ends = []


def on_job_new(id, job, unit):
    job_starts.append(dict(id=id, job=job, unit=unit))
    print(f"new job {id=} {job=} {unit=}")


def on_job_remove(id, job, unit, result):
    job_ends.append(dict(id=id, job=job, unit=unit, result=result))
    print(f"job removed {id=} {job=} {unit=} {result=}")


async def system_start():
    bus = await MessageBus().connect()
    systemd_prox = await make_proxy(bus, SYSTEMD_BUS_NAME, SYSTEMD_OBJECT_PATH)

    manager = systemd_prox.get_interface(SYSTEMD_MANAGER_IFACE)
    manager.on_job_new(on_job_new)  # type: ignore
    manager.on_job_removed(on_job_remove)  # type: ignore
    await manager.call_subscribe()  # type: ignore

    crc_path = await manager.call_load_unit("crc.service")  # type: ignore
    crc_proxy = await make_proxy(bus, SYSTEMD_BUS_NAME, crc_path)
    crc_unit = crc_proxy.get_interface(SYSTEMD_UNIT_IFACE)

    await crc_unit.call_start("fail")  # type: ignore

    while True:
        state = UnitActiveState(await crc_unit.get_active_state())  # type: ignore
        match state:
            case UnitActiveState.activating:
                # TODO: crc status instead?
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
            case UnitActiveState.failed:
                sys.exit("starting user crc process failed")
            case UnitActiveState.active:
                _notify(ready=True, status="unit state is active")
            case _:
                print(f"state {state}")


match sys.argv[1]:
    case "log_statuses":
        watch_and_log_statuses()
    case "start":
        start()
    case "system-start":
        # TODO: I can't run the following to get these values, despite its own guidance
        # print(subprocess.run("systemctl --machine=kevin@.host --user show-environment".split(), text=True, check=True).stdout)
        uid = os.getuid()
        os.environ["XDG_RUNTIME_DIR"] = f"/run/user/{uid}"
        os.environ["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{uid}/bus"
        asyncio.run(system_start())
    case _:
        sys.exit(f"Unknown command {sys.argv[1]}")
