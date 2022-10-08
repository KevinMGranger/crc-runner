import logging


def setup():
    try:
        from systemd.journal import JournalHandler

        logging.root.addHandler(JournalHandler())
    except NameError:
        pass

    logging.root.setLevel(logging.DEBUG)
