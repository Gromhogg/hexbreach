"""The IDS slot. An IDS sits at the end of every subnet and holds one of
several games, which you do not know until you get there, plus view effects
on the hex dump (LOSS, THROTTLE...) that come on at higher levels."""
import random

from .base import HOPS, MODES_ALL, Puzzle, at, step

# name -> what it does to the hex view
MODIFIERS = {
    "LOSS": "some bytes never arrive (??)",
    "BLACKOUT": "ASCII pane hidden",
    "THROTTLE": "rate-limited: the dump arrives a few rows a second",
    "BLIND": "offset column hidden",
    "DARK": "only bytes near the cursor are visible",
}
# an IDS sits at the end of its subnet, so the five of them are levels 2 to 6
MOD_COUNT = [(at(1), 1), (at(4), 2), (at(6), 3)]
# the level from which each modifier can be drawn: the mild ones come first
MOD_FROM = {"THROTTLE": at(1), "BLACKOUT": at(1), "BLIND": at(1), "LOSS": at(3), "DARK": at(4)}


class IdsPuzzle(Puzzle):
    """What every IDS game shares. Not in REGISTRY: the boss is built straight
    from the node by generate() below, never dealt onto the map."""
    kind = "IDS"
    modes = MODES_ALL
    first = at(1, HOPS + 1)
    PAY = 1.0               # the IDS pays by its own rule (run.score), not this

    def __init__(self, seed, level):
        super().__init__(seed, level)
        self.modifiers = []

    @classmethod
    def generate(cls, seed, source, level, modifiers=()):
        raise NotImplementedError


def generate(seed, source, level):
    """The IDS at a node: draw its view effects, then the game it holds."""
    rng = random.Random(seed)
    pool = sorted(m for m in MODIFIERS if MOD_FROM[m] <= level)
    modifiers = rng.sample(pool, step(level, MOD_COUNT))
    games = [g for g in GAMES if g.first <= level] or GAMES[:1]     # practice may ask for a level below the first IDS
    return rng.choice(games).generate(seed, source, level, modifiers)


# the games come last: each one imports IdsPuzzle from this module
from .alertlog import AlertLog      # noqa: E402
GAMES = (AlertLog,)                 # a tuple: an uppercase list in this module reads as a difficulty table
