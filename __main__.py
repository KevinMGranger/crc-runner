#!/usr/bin/python
import asyncio
import asyncio.subprocess as aproc
import datetime
import logging
from signal import SIGINT, SIGTERM
import subprocess
import sys
import syslog
from asyncio import CancelledError
from typing import Any, Coroutine

from dbus_next.aio import MessageBus, ProxyObject
from dbus_next.service import ServiceInterface, method
from systemd import journal

from crc_systemd import crc, dbus, systemd
from crc_systemd.crc import SpawningStop, Stopping
from crc_systemd.async_helpers import SignalError, check_signal
from crc_systemd.dbus import make_proxy
from crc_systemd.systemd import Notify, UnitActiveState

POLL_INTERVAL_SECONDS = 6

log = logging.getLogger(__name__)


class UserCrcRunner(ServiceInterface):
    "Starts and monitors CRC, reacting to a stop request by shutting it down."

    def __init__(self, bus: MessageBus, start_proc: aproc.Process):
        super().__init__("fyi.kmg.crc_runner.Runner1")
        self.bus = bus
        self.start_proc = start_proc
        self.start_task = asyncio.create_task(start_proc.wait())
        self.monitor = crc.CrcMonitor(POLL_INTERVAL_SECONDS)
        self.stop_state: SpawningStop | Stopping | None = None

    @method(name="stop")
    async def dbus_stop(self):
        await self.stop("dbus")

    async def stop(self, source: str):
        log.info(f"Stopping from {source}")
        while True:
            match self.stop_state:
                case None:
                    self.stop_state = SpawningStop(asyncio.create_task(crc.stop()))
                    # here just in case it throws, so the stop task can still start
                    Notify.stopping()

                    # do this regardless to avoid race condition:
                    # time between check and use
                    # (although does this even signal it? Does it even need to?)
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
                    self.bus.disconnect()
                    return

    async def __call__(self):
        try:
            # TODO: this could totally be a context manager
            returncode = await check_signal(self.start_task, SIGTERM)
            if returncode != 0:
                output = str(await self.start_proc.stdout.read())  # type: ignore
                log.error(output)
                raise subprocess.CalledProcessError(returncode, "crc start", output)

            # wait for successful status
            log.info("Waiting for CRC to successfuly start")
            await check_signal(self.monitor.ready.wait(), SIGTERM)
            Notify.ready("CRC Started")
        except SignalError as e:
            log.info("Got SIGTERM, stopping CRC")
            await self.stop("SIGTERM")
            sys.exit(128 + e.signal.value)
        except CancelledError:
            log.info("Cancelled, stopping")
            await self.stop("cancellation")

        log.debug("Disconnecting from bus")
        await self.bus.wait_for_disconnect()


class SystemCrcUserRunner(ServiceInterface):
    """
    Starts and watches the user-level CRC service.
    Meant to be paired with a system-level HAProxy.
    """

    def __init__(self, bus: MessageBus, systemd_prox: ProxyObject):
        self.bus = bus
        self.systemd_prox = systemd_prox
        self.systemd_manager = systemd_prox.get_interface(systemd.MANAGER_IFACE)
        self.crc_unit = None
        self.monitoring = None

    async def start(self):
        crc_path = await self.systemd_manager.call_load_unit("crc.service")  # type: ignore
        crc_proxy = await make_proxy(self.bus, systemd.BUS_NAME, crc_path)
        self.crc_unit = crc_unit = crc_proxy.get_interface(systemd.UNIT_IFACE)

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
                    Notify.ready("unit state is active")
                    return
                case UnitActiveState.inactive:
                    raise Exception("Inactive for some reason?")
                case UnitActiveState.deactivating:
                    raise Exception("Deactivating for some reason?")
                case UnitActiveState.reloading:
                    print("Reloading, idk")
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def monitor(self):
        self.monitoring = monitoring = asyncio.create_task(
            self._monitor(), name="user service monitor"
        )
        try:
            await monitoring
        except asyncio.CancelledError:
            return

    async def _monitor(self):
        while True:
            match await self.crc_unit.get_active_state():  # type: ignore
                case UnitActiveState.failed:
                    sys.exit("user crc process failed")
                case UnitActiveState.active:
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)
                case UnitActiveState.deactivating:
                    Notify.stopping()
                case UnitActiveState.inactive:
                    return

    @method()
    async def stop(self):
        if self.crc_unit is None:
            return

        if self.monitoring is not None and not self.monitoring.done():
            self.monitoring.cancel(msg="stop requested")

        while True:
            match await self.crc_unit.get_active_state():  # type: ignore
                case UnitActiveState.activating:
                    Notify.stopping()
                    await self.crc_unit.call_stop("replace")  # type: ignore
                case UnitActiveState.active:
                    Notify.stopping()
                    await self.crc_unit.call_stop("replace")  # type: ignore
                case UnitActiveState.failed:
                    sys.exit("user crc process failed")
                case UnitActiveState.inactive:
                    self.bus.disconnect()
                    return
                case UnitActiveState.deactivating:
                    Notify.stopping()
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)
                case UnitActiveState.reloading:
                    print("Reloading, idk")
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def start():
    print("Connecting to dbus", flush=True)
    bus = await dbus.connect()
    print("Starting CRC instance")
    runner = UserCrcRunner(bus, await crc.start())
    bus.export("/fyi/kmg/crc_runner/Runner1", runner)
    await bus.request_name("fyi.kmg.crc_runner")
    await runner()


async def system_start():
    print("Connecting to dbus")
    bus = await dbus.connect()
    print("Asking user session to start CRC")
    runner = SystemCrcUserRunner(bus, await systemd.karen(bus))
    # TODO: hang on, this is different!
    # We need the user bus to communicate with the systemd session there,
    # but we need the system bus to listen for stop requests ourselves!
    bus.export("/fyi/kmg/crc_runner/SysRunner1", runner)
    await bus.request_name("fyi.kmg.crc_runner")
    await runner.start()
    await runner.monitor()
    await bus.wait_for_disconnect()


async def log_statuses():
    while True:
        _status = await crc.status()
        print(datetime.datetime.now(), _status)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


match sys.argv[1]:
    case "log_statuses":
        asyncio.run(log_statuses())
    case "start":
        asyncio.run(start())
    case "system-start":
        dbus.session_bus_env_setup()
        asyncio.run(system_start())
    case _:
        sys.exit(f"Unknown command {sys.argv[1]}")
