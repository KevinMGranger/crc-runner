import logging

from systemd.journal import JournalHandler

from ._systemd import under_systemd


def setup():
    if under_systemd():
        # TODO: will this use some sort of default format and mess with things? I don't think so but check.
        logging.basicConfig(handlers=(JournalHandler(),), level=logging.DEBUG)
    else:
        logging.basicConfig(format="%(asctime)s %(message)s", level=logging.DEBUG)
