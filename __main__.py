#!/usr/bin/python

import asyncio
import asyncio.subprocess as aproc
import subprocess
import sys

from dbus_next.aio import MessageBus, ProxyObject
from dbus_next.service import ServiceInterface, method

from crc_systemd import crc, dbus, systemd
from crc_systemd.dbus import make_proxy
from crc_systemd.systemd import Notify, UnitActiveState

POLL_INTERVAL_SECONDS = 6
LOG_INFO = 6


class CrcRunner(ServiceInterface):
    stop_proc: aproc.Process | None

    def __init__(self, bus: MessageBus, start_proc: aproc.Process):
        super().__init__("fyi.kmg.crc_runner.Runner1")
        self.bus = bus
        self.start_proc = start_proc
        self.stop_proc = None

    # async def start(self):
    #     Notify.notify(status="Starting CRC instance")
    #     self.start_proc = await crc.start()
    #     # match await start.wait():
    #     #     case 0:
    #     #         Notify.ready(status="CRC Started")

    async def _handle_stop(self, returncode: int):
        if returncode == 0:
            self.stop_proc = await crc.stop()
            await self.stop_proc.wait()
            return

        status = await crc.status()

        if status.crc_status == crc.CrcStatus.stopped:
            return
        elif status.openshift_status == status.openshift_status.stopped:
            return

        self.stop_proc = await crc.stop()
        await self.stop_proc.wait()

    @method()
    async def stop(self):
        Notify.stopping()
        if self.start_proc.returncode is None:
            self.start_proc.terminate()
            returncode = await self.start_proc.wait()
        else:
            returncode = self.start_proc.returncode

        await self._handle_stop(returncode)

        self.bus.disconnect()

    # TODO: should keep track of the start task so it can be cancelled correctly
    # requires refactoring / coordinating between wait_for_start as well as stop

    async def wait_for_start(self):
        returncode = await self.start_proc.wait()
        if returncode == 0:
            Notify.ready("CRC Started")
        else:
            raise subprocess.CalledProcessError(returncode, "crc start")


class CrcUserServiceRunner(ServiceInterface):
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
    print("Connecting to dbus")
    bus = await dbus.connect()
    print("Starting CRC instance")
    runner = CrcRunner(bus, await crc.start())
    bus.export("/fyi/kmg/crc_runner/Runner1", runner)
    await bus.request_name("fyi.kmg.crc_runner")
    asyncio.create_task(crc.monitor(POLL_INTERVAL_SECONDS))
    await runner.wait_for_start()
    await bus.wait_for_disconnect()


async def system_start():
    print("Connecting to dbus")
    bus = await dbus.connect()
    print("Asking user session to start CRC")
    runner = CrcUserServiceRunner(bus, await systemd.karen(bus))
    bus.export("/fyi/kmg/crc_runner/SysRunner1", runner)
    await bus.request_name("fyi.kmg.crc_runner")
    await runner.start()
    await runner.monitor()
    await bus.wait_for_disconnect()


match sys.argv[1]:
    case "log_statuses":
        asyncio.run(crc.monitor(POLL_INTERVAL_SECONDS))
    case "start":
        asyncio.run(start())
    case "system-start":
        dbus.session_bus_env_setup()
        asyncio.run(system_start())
    case _:
        sys.exit(f"Unknown command {sys.argv[1]}")
