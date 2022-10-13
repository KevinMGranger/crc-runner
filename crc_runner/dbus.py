import os
from contextlib import asynccontextmanager

import dbus_next.aio as aio
from dbus_next.constants import BusType


async def make_proxy(bus, bus_name, path) -> aio.ProxyObject:
    "Get a proxy object for the specified object, automatically doing introspection"
    return bus.get_proxy_object(bus_name, path, await bus.introspect(bus_name, path))


async def connect(bus_type: BusType = BusType.SESSION) -> aio.MessageBus:
    return await aio.MessageBus(bus_type=bus_type).connect()


def session_bus_env_setup():
    # TODO: I can't run the following to get these values, despite its own guidance
    # print(subprocess.run("systemctl --machine=kevin@.host --user show-environment".split(), text=True, check=True).stdout)
    uid = os.getuid()
    os.environ["XDG_RUNTIME_DIR"] = f"/run/user/{uid}"
    os.environ["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{uid}/bus"


@asynccontextmanager
async def bus_connection():
    bus = await connect()
    try:
        yield bus
    except:
        bus.disconnect()
        raise
