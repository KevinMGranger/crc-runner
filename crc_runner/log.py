import logging

from .systemd import under_systemd


def setup():
    try:
        from systemd.journal import JournalHandler

        if under_systemd():
            logging.root.addHandler(JournalHandler())
    except NameError:
        pass

    logging.root.setLevel(logging.DEBUG)
