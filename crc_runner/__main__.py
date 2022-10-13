#!/usr/bin/python3
import asyncio
import logging
import sys

from crc_runner import dbus, system, user
from crc_runner.log import setup as setup_logging

POLL_INTERVAL_SECONDS = 6

log = logging.getLogger(__name__)


def main():
    setup_logging()

    if len(sys.argv) != 2:
        sys.exit("Usage: crc-runner start|system-start")

    match sys.argv[1]:
        case "start":
            asyncio.run(user.run())
        case "system-start":
            dbus.session_bus_env_setup()
            asyncio.run(system.run())
        case _:
            sys.exit(f"Unknown command {sys.argv[1]}")


if __name__ == "__main__":
    main()
