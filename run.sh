#!/bin/bash
# Start HEXBREACH. Creates the virtualenv on first run.
cd "$(dirname "$0")" || exit 1

# The starting-up popup (splash/, startup.py): a separate small program, so it
# is on screen at once and keeps moving while Python and pygame load. The game
# gets a pipe to it as fd 3 and never waits for it. With no popup (not built,
# not a Mac, or it dies) the game starts exactly as it would without one.
splash=splash/hexbreach-splash
if [ -n "$BASH_VERSION" ] && [ -x "$splash" ] && [ -z "$HEXBREACH_NO_SPLASH" ]; then
    mode=start
    [ -x .venv/bin/python ] || mode=setup       # first run: the install takes a while
    set +o posix                                # run as "sh run.sh", bash has >( ) switched off
    eval 'exec 3> >(exec "./$splash" "$mode" "$$" 2>/dev/null)' && export HEXBREACH_SPLASH_FD=3
fi

if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt || exit 1
fi
. .venv/bin/activate
exec python main.py "$@"
