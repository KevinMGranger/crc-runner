#!/usr/bin/python
import asyncio
import logging
import sys

from dbus_next.aio import MessageBus, ProxyObject
from dbus_next.service import ServiceInterface, method

from crc_runner import dbus, systemd
from crc_runner.dbus import make_proxy
from crc_runner.systemd import Notify, UnitActiveState

POLL_INTERVAL_SECONDS = 6

log = logging.getLogger(__name__)


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


async def run():
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
