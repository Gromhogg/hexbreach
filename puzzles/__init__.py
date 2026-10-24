"""One module per puzzle type. Puzzles only ever talk to a ByteSource."""
from .base import (HOPS, MODES_ALL, MODES_PACKET, NEAR, WILD, WRONG, Puzzle, PuzzleUnavailable, apply_actions, at,
                   ramp, step)
from .payload import Payload
from .checksum import Checksum
from .dissect import Dissect
from .hunt import Hunt
from .ids import MODIFIERS, IdsPuzzle
from .carve import SELF_NAMING, SIGNATURES, Carve
from .reassemble import Reassemble
from .xor import Xor

REGISTRY = {cls.kind: cls for cls in (Payload, Hunt, Xor, Dissect, Checksum, Carve, Reassemble)}
# kinds that work on any bytes at all; used when a packet puzzle cannot be built
ANY_BYTES = ("PAYLOAD", "HUNT", "CARVE")


def kinds_for_mode(mode, level=None):
    """Puzzle kinds a data mode offers, in the order they come into play.
    With a level, only the kinds that have started turning up by then."""
    kinds = sorted((cls for cls in REGISTRY.values() if mode in cls.modes), key=lambda cls: cls.first)
    return [cls.kind for cls in kinds if level is None or cls.first <= level]


def generate(kind, seed, source, level, solved=None):
    """Generate a puzzle, stepping the seed if a particular draw cannot be
    built, and falling back to a bytes-only puzzle as a last resort (a LIVE
    capture with no IPv4 in it, say). solved is how many nodes of this kind
    the run has solved so far: a kind with levels of its own goes by that."""
    cls = REGISTRY[kind]
    own = {"solved": solved} if cls.own_levels else {}
    for attempt in range(8):
        try:
            return cls.generate(seed + attempt, source, level, **own)
        except PuzzleUnavailable:
            continue
    fallback = ANY_BYTES[seed % len(ANY_BYTES)]
    return REGISTRY[fallback].generate(seed, source, level)
