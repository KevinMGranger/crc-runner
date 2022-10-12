import enum

import systemd.daemon
from dbus_next.aio import MessageBus

from crc_runner import dbus


class Notify:
    @staticmethod
    def _notify(messages: dict[str, str]) -> str:
        return "\n".join((f"{kw}={val}" for kw, val in messages.items()))

    @staticmethod
    def notify(
        status: str | None = None,
        **messages: str,
    ):
        if status:
            messages["STATUS"] = status

        msg = "\n".join((f"{kw}={val}" for kw, val in messages.items()))
        systemd.daemon.notify(msg)

    @staticmethod
    def ready(
        status: str | None = None,
        **messages: str,
    ):
        Notify.notify(READY="1", status=status, **messages)

    @staticmethod
    def stopping(
        status: str | None = None,
        **messages: str,
    ):
        Notify.notify(STOPPING="1", status=status, **messages)


class UnitActiveState(enum.Enum):
    active = "active"
    reloading = "reloading"
    inactive = "inactive"
    failed = "failed"
    activating = "activating"
    deactivating = "deactivating"


BUS_NAME = "org.freedesktop.systemd1"
OBJECT_PATH = "/org/freedesktop/systemd1"

MANAGER_IFACE = "org.freedesktop.systemd1.Manager"
SERVICE_IFACE = "org.freedesktop.systemd1.Service"
UNIT_IFACE = "org.freedesktop.systemd1.Unit"


def karen(bus: MessageBus):
    "Ask to speak to the (systemd) manager"
    return dbus.make_proxy(bus, BUS_NAME, MANAGER_IFACE)
