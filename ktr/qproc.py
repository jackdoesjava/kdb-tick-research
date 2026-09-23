"""Start and stop q processes from Python.

Scripts and tests both need to bring up a TP/RDB/checks/HDB set, so this is
shared. q is found from the QEXE environment variable, then $QHOME/w64/q.exe
(Windows) or $QHOME/l64/q, then PATH.
"""

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def find_q():
    if os.environ.get("QEXE"):
        return os.environ["QEXE"]
    qhome = os.environ.get("QHOME", str(Path.home() / "kx"))
    for sub in ("w64/q.exe", "l64/q", "m64/q"):
        p = Path(qhome) / sub
        if p.exists():
            return str(p)
    q = shutil.which("q")
    if q is None:
        raise FileNotFoundError("can't find q; set QEXE or QHOME")
    return q


def port_open(port):
    with socket.socket() as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", port)) == 0


class QProc:
    """One q process listening on a port. Use as a context manager."""

    def __init__(self, script, port, args=(), log=None, cwd=ROOT):
        self.port = port
        cmd = [find_q(), str(script), "-p", str(port), *map(str, args)]
        env = dict(os.environ)
        env.setdefault("QHOME", str(Path.home() / "kx"))
        out = open(log, "a") if log else subprocess.DEVNULL
        self.p = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                  stdout=out, stderr=subprocess.STDOUT)
        self._wait_up()

    def _wait_up(self, timeout=20):
        t0 = time.time()
        while not port_open(self.port):
            if self.p.poll() is not None:
                raise RuntimeError(f"q exited with code {self.p.returncode} before opening port {self.port}")
            if time.time() - t0 > timeout:
                self.stop()
                raise TimeoutError(f"q didn't open port {self.port}")
            time.sleep(0.05)

    def stop(self):
        if self.p.poll() is None:
            self.p.kill()
            self.p.wait()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stop()


def connect(port):
    # IPC works in PyKX's unlicensed mode, which is all we need from Python
    os.environ.setdefault("PYKX_UNLICENSED", "true")
    import pykx as kx
    return kx.SyncQConnection(host="localhost", port=port)


def wait_for_day(conn, var, day, timeout=900):
    """Poll a date variable in a q process (e.g. .rdb.saved) until it
    equals day. Subscribers get the TP's messages asynchronously, so this is
    how a script knows one has caught up with the end of a day."""
    t0 = time.time()
    while str(conn(var).py()) != str(day):
        if time.time() - t0 > timeout:
            raise TimeoutError(f"{var} never reached {day}")
        time.sleep(0.5)


if __name__ == "__main__":
    print(find_q(), file=sys.stderr)
