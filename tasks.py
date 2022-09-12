from pathlib import Path
import shutil
from invoke import task

DOWNLOADS_URL = "https://developers.redhat.com/content-gateway/rest/mirror/pub/openshift-v4/clients/crc/"
FILENAME = "crc-linux-amd64.tar.xz"

# TODO LATER: version-independent folder
CRC_DOWNLOADED_DIR = Path("./crc-linux-2.8.0-amd64")
CRC_DOWNLOADED_BIN = CRC_DOWNLOADED_DIR / "crc"
CRC_LOCAL_BIN = Path.home() / ".crc/bin/crc"

@task
def download_linux(c):
    c.run(f"curl -L {DOWNLOADS_URL}/latest/{FILENAME} -O")

@task
def extract(c):
    c.run(f"tar xf {FILENAME}")

@task
def clean_download_dir(c):
    shutil.rmtree(CRC_DOWNLOADED_DIR)

@task
def crc_setup(c, verbose=False):
    if CRC_DOWNLOADED_BIN.exists():
        crc_bin = CRC_DOWNLOADED_BIN
    elif CRC_LOCAL_BIN.exists():
        crc_bin = CRC_LOCAL_BIN
    else:
        raise FileNotFoundError("No CRC bin found")

    c.run(f"{crc_bin} config set consent-telemetry yes")
    c.run(f"{crc_bin} config set pull-secret-file ~/crc_pull_secret")

    # GB to MB
    memory = 20 * 1024 

    c.run(f"{crc_bin} config set memory {memory}")
    c.run(f"{crc_bin} config set disk-size 64")
    log = "--log-level 9" if verbose else ""
    c.run(f"{crc_bin} setup {log}", pty=True)

    # overwrite symlink with actual binary
    if CRC_LOCAL_BIN.resolve() == CRC_DOWNLOADED_BIN.resolve():
        CRC_DOWNLOADED_BIN.rename(CRC_LOCAL_BIN)