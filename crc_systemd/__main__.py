#!/usr/bin/python
import asyncio
import logging
import sys


from crc_systemd import dbus, system, user
from crc_systemd.log import setup as setup_logging

POLL_INTERVAL_SECONDS = 6

log = logging.getLogger(__name__)


setup_logging()

match sys.argv[1]:
    case "start":
        asyncio.run(user.run())
    case "system-start":
        dbus.session_bus_env_setup()
        asyncio.run(system.run())
    case _:
        sys.exit(f"Unknown command {sys.argv[1]}")
