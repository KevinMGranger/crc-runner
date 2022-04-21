#!/usr/bin/python
import asyncio
import asyncio.subprocess as aproc
import datetime
import subprocess
import sys
import syslog
from asyncio import CancelledError

from dbus_next.aio import MessageBus, ProxyObject
from dbus_next.service import ServiceInterface, method
from systemd import journal

from crc_systemd import crc, dbus, systemd
from crc_systemd.dbus import make_proxy
from crc_systemd.systemd import Notify, UnitActiveState

POLL_INTERVAL_SECONDS = 6


class CrcRunner(ServiceInterface):
    stop_proc: aproc.Process | None

    def __init__(self, bus: MessageBus, start_proc: aproc.Process):
        super().__init__("fyi.kmg.crc_runner.Runner1")
        self.bus = bus
        self.start_proc = start_proc
        self.start_task = asyncio.create_task(start_proc.wait())
        self.stop_proc = None

    # async def start(self):
    #     Notify.notify(status="Starting CRC instance")
    #     self.start_proc = await crc.start()
    #     # match await start.wait():
    #     #     case 0:
    #     #         Notify.ready(status="CRC Started")


    @method()
    async def stop(self):
        Notify.stopping()

        # this will not be called if still starting!
        # We will get a signal instead,
        # so we don't need to wait as long as we notify correctly

        self.stop_proc = await crc.stop()
        await self.stop_proc.wait()

        # crap, waas this all even necessary?
        # you fundamentally can't exit without the signal
        # because once you reply the call exits, and if it's still up you get signal (what)
        
        self.bus.disconnect()
        await self.bus.wait_for_disconnect()

    async def __call__(self):
        # TODO: can crc start fail but still have the vm running?
        # crc stop will "work" even if it's already stopped.
        # it'll return 1, but we can ignore that since we're
        # already in a defacto
        # error handler / exception handler / destructor

        # TODO: is it okay to call terminate on an already-exited process?

        # TODO:how do we fit waiting on the bus into here?
        # do we even need to?
        # I guess we do in the happy path
        try:
            returncode = await self.start_task
            if returncode == 0:
                Notify.ready("CRC Started")
            else:
                raise subprocess.CalledProcessError(returncode, "crc start")
            
            await self.bus.wait_for_disconnect()
        except CancelledError:
            self.start_proc.terminate()
            raise
        finally:
            self.bus.disconnect()



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
    print("Connecting to dbus", flush=True)
    bus = await dbus.connect()
    print("Starting CRC instance")
    runner = CrcRunner(bus, await crc.start())
    bus.export("/fyi/kmg/crc_runner/Runner1", runner)
    await bus.request_name("fyi.kmg.crc_runner")
    asyncio.create_task(crc.monitor(POLL_INTERVAL_SECONDS))
    await runner()


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
