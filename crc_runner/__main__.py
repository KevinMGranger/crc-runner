#!/usr/bin/python3
import asyncio
import logging
import os
import sys

from crc_runner import dbus, system, user
from crc_runner.log import setup as setup_logging

POLL_INTERVAL_SECONDS = 6


def main():
    setup_logging()
    logging.debug("Running from %s; path: %s, env var: %s", __file__, sys.path, os.environ.get("PYTHONPATH", ""))

    if len(sys.argv) != 2:
        sys.exit("Usage: crc-runner start|system-start")

    match sys.argv[1]:
        case "start":
            asyncio.run(user.run())
        case "system-start":
            dbus.session_bus_env_setup()
            asyncio.run(system.run())
        case "checkrun":
            pass
        case _:
            sys.exit(f"Unknown command {sys.argv[1]}")


if __name__ == "__main__":
    main()
