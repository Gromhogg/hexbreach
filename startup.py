"""The game's line to the starting-up popup: how far along the start is.

run.sh starts the popup (splash/) before Python, and hands the game a pipe to
it: the file descriptor named by HEXBREACH_SPLASH_FD. The game writes one line
per step of its start, "55 opening display", and then "done". It never waits
for the popup. With no popup (the tests, python main.py, a popup that has
died) every call here does nothing."""
import os
import stat
import time

_fd = None
_slow = 0.0     # HEXBREACH_SLOW_START: seconds to wait at each step, to watch the popup work


def connect():
    """Take up the pipe run.sh left, if it left one."""
    global _fd, _slow
    _drop()
    try:
        fd = int(os.environ.pop("HEXBREACH_SPLASH_FD", ""))
        if fd < 3 or not stat.S_ISFIFO(os.fstat(fd).st_mode):
            return
        os.set_blocking(fd, False)      # a popup that has stopped reading must not stop the game
        os.set_inheritable(fd, False)
        _slow = float(os.environ.get("HEXBREACH_SLOW_START", 0))
    except (ValueError, OSError):
        return
    _fd = fd


def _drop():
    global _fd
    fd, _fd = _fd, None     # forgotten before it is closed: the number goes to the next file opened
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass


def _send(line):
    if _fd is None:
        return
    try:
        os.write(_fd, line)
    except BlockingIOError:
        pass                # the pipe is full: the popup can do without this line
    except OSError:
        _drop()             # the popup has gone


def step(percent, label):
    """The start has got this far; label is what it is about to do."""
    if _fd is None:
        return
    _send(b"%d %s\n" % (percent, label.encode()))
    if _slow:
        time.sleep(_slow)


def done():
    """The first frame is on screen: the popup can go."""
    _send(b"done\n")
    _drop()


connect()
