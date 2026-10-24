"""Puzzle base class.

A puzzle is pure logic: no pygame, no knowledge of where its bytes came from.
Each one has generate(seed, source, level), a validator and a known solution,
plus a small interactive surface (click / select / key) that the puzzle scene
drives and that the tests can drive headlessly.

Difficulty is one number, the level, and it rises with every hop: the subnet
number plus how far through that subnet the node is. at(1, 1) = 1.0 is the
first node of a run, at(5, 7) = 6.0 is the last IDS. Each puzzle's settings
sit in tables at the top of its class, read with ramp() (numbers that change
smoothly) or step() (settings that change in jumps).

Inputs return one of:
    None       nothing happened
    "ok"       progress
    "mistake"  wrong; costs TRACE
    "solved"   done

A mistake has a severity, which sets how much TRACE it costs: NEAR for a slip
by someone who plainly understood the puzzle, WILD for a stab in the dark,
WRONG for anything in between. Each puzzle judges its own.
"""

MODES_ALL = frozenset({"RAW", "PROTOCOL", "LIVE"})
MODES_PACKET = frozenset({"PROTOCOL", "LIVE"})

HEX_DIGITS = "0123456789abcdef"

NEAR, WRONG, WILD = "near", "wrong", "wild"     # how bad a mistake was

HOPS = 6            # ordinary nodes on the way through a subnet; the IDS is hop HOPS + 1


def at(subnet, hop=1):
    """The level at a hop of a subnet. Levels run on from one subnet into the
    next: the IDS of subnet 1, at(1, 7), is level 2.0, the same as at(2, 1)."""
    return subnet + (hop - 1) / HOPS


def ramp(level, table):
    """A number that changes smoothly with level. The table holds its value at
    the start of each subnet (levels 1, 2, 3...) and, last, at the final IDS;
    levels in between are interpolated."""
    x = max(0.0, min(level - 1, len(table) - 1))
    i = min(int(x), len(table) - 2)
    return table[i] + (table[i + 1] - table[i]) * (x - i)


def step(level, table):
    """A setting that changes in jumps. The table is (from level, value) pairs
    in rising order; the last pair whose level has been reached applies."""
    value = table[0][1]
    for start, v in table:
        if level >= start:
            value = v
    return value


WIDTHS = [8, 10, 12, 16]    # bytes a row a dump may be drawn with


def pick_cols(rng):
    """A width for the dump, so not every table is 16 bytes a row."""
    return rng.choice(WIDTHS)


def spread(rng, size, cols, amount=0.35):
    """A dump size near size, give or take amount of it, in whole rows of cols:
    so nodes of the same level are not all the same height."""
    size = size * rng.uniform(1 - amount, 1 + amount)
    return max(3, round(size / cols)) * cols


def hexs(data):
    return " ".join("%02X" % b for b in data)


# Code page 437, the character set of the first IBM PCs: a symbol for every
# byte value, where ASCII has a character for only 95 of the 256. The real one
# leaves 00 and FF blank; here they get a symbol too, so no two bytes look alike.
CP437 = ("\u2205\u263a\u263b\u2665\u2666\u2663\u2660\u2022\u25d8\u25cb\u25d9\u2642\u2640\u266a\u266b\u263c"
         "\u25ba\u25c4\u2195\u203c\u00b6\u00a7\u25ac\u21a8\u2191\u2193\u2192\u2190\u221f\u2194\u25b2\u25bc"
         + "".join(map(chr, range(32, 127))) + "\u2302" + bytes(range(128, 255)).decode("cp437") + "\u25a1")


def printable(data, codepage=False):
    """The bytes as they read in the ASCII pane: a dot for a byte that is not
    a printable character or, with the CODEPAGE tool, its own symbol."""
    if codepage:
        return "".join(CP437[b] for b in data)
    return "".join(chr(b) if 32 <= b < 127 else "." for b in data)


def count(n, word):
    """'1 file', '3 files'."""
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def nth(n):
    """'1st', '2nd', '11th'."""
    return "%d%s" % (n, "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))


# ---- a briefing's example: a few frames, played on a loop
STEP, BEAT, REST = 0.3, 0.9, 2.2    # seconds a frame stays up: the pointer moving, something happening, the end


def cells(data, styles=None):
    """A line of dump for an example: the bytes in hex, as (text, style)
    pieces. styles is {index: a hex view style}; the rest are dim. A highlight
    runs through the gap between two bytes that share it, as in the dump."""
    styles, out = styles or {}, []
    for i, b in enumerate(data):
        style = styles.get(i, "dim")
        if i:
            _piece(out, " ", style if styles.get(i - 1, "dim") == style else "dim")
        _piece(out, "%02X" % b, style)
    return out


def _piece(out, text, style):
    if out and out[-1][1] == style:
        out[-1] = (out[-1][0] + text, style)
    else:
        out.append((text, style))


def pointer(i, note=""):
    """The line under cells(): the mouse, below byte i, and what it does there."""
    return [(" " * (3 * i) + "▲" + (" " + note if note else ""), "tan")]


def walk(a, b):
    """The bytes the pointer passes on its way from a to b: a itself left out, b included."""
    return range(a + 1, b + 1) if b >= a else range(a - 1, b - 1, -1)


class PuzzleUnavailable(Exception):
    """Raised by generate() when the source cannot supply what the puzzle needs."""


class Puzzle:
    kind = "?"
    modes = MODES_ALL
    first = at(1, 1)            # level at which this kind starts turning up on the map
    select_mode = "click"       # "click": single bytes, "drag": byte ranges, "move": drag bytes from one place to another
    codepage = False            # the CODEPAGE tool is held: the ASCII pane has a symbol for every byte
    blurb = ""                  # the job in one line: the line above the dump for a kind that lists no tasks
    what = ""                   # the kind of job this is, in a line; what comes before its colon is its real name
    do = ""                     # what you do here, in a few words: the first row of the briefing
    PAY = 1.0                   # how hard the kind is: what it pays, as a multiple of the going rate
    own_levels = False          # True for a kind with levels of its own, climbed one solved node at a time (XOR)

    def __init__(self, seed, level):
        self.seed = seed
        self.level = level
        self.data = bytearray()
        self.time_limit = 60.0
        self.solution = None
        self.solved = False
        self.rank = None        # (name, pay multiplier) once solved, for a kind with ranks()
        self.mistakes = 0
        self.severity = WRONG   # of the latest mistake
        self.messages = []      # (text, colour key), drained by the scene into the log
        self.learned = []       # ("field", name, example) / ("signature", name, hex)
        self.flash = {}         # byte index -> seconds left of hint highlight
        self.packet = None      # parsed Packet when the dump is one frame
        self.cols = 16          # bytes a row in the dump
        self.drag = None        # "move" kinds: (byte picked up, byte under the mouse or None) while dragging

    # ---- generation / checking
    @classmethod
    def generate(cls, seed, source, level):
        raise NotImplementedError

    def validate(self, answer):
        raise NotImplementedError

    def difficulty(self):
        """How hard this node came out, next to others of its kind and level:
        1.0 is usual, lower is an easy roll. It scales the base pay."""
        return 1.0

    def ranks(self):
        """A kind that can be passed at more than one rank lists them here,
        lowest first: (name, pay multiplier). Empty for a plain pass or fail."""
        return []

    def solution_actions(self):
        """The known solution as inputs: ("click", i) ("select", lo, hi)
        ("move", src, dst) ("type", text) ("key", name)."""
        raise NotImplementedError

    # ---- input
    def click(self, idx):
        return None

    def select(self, lo, hi):
        return None

    def move(self, src, dst):
        """"move" kinds: the byte at src was dragged and let go over dst
        (None: outside the dump)."""
        return None

    def key(self, k):
        """k is a single lower-case character, "enter" or "backspace"."""
        return None

    # ---- display
    def display(self):
        return self.data

    def styles(self):
        return {}

    def tasks(self):
        """The job as steps, in order: (text, state) with state "done", "now"
        or "todo". One step is "now" until the puzzle is solved; then all are
        "done". One to five steps in plain words, saying what, not how to
        click; a step may end with a live count ("(1/3)")."""
        return []

    def _ordered(self, texts, now):
        """tasks() for a job done in order: the steps before now are done, now
        is current, the rest to do. Solved, every step is done."""
        if self.solved:
            return [(t, "done") for t in texts]
        return [(t, "done" if i < now else "now" if i == now else "todo") for i, t in enumerate(texts)]

    def prompt(self):
        """The line above the dump: the current step, or the blurb for a kind that lists no steps."""
        return next((text for text, state in self.tasks() if state == "now"), self.blurb)

    def summary(self):
        """What is on this node, in a line."""
        return ""

    def brief(self):
        """The briefing, read before the timer starts: a few (label, text)
        rows, each short enough to take in at a glance. The first says what to
        do; the rest are what is on this node, so no two nodes brief alike."""
        return [("DO", self.do)]

    def example(self):
        """The job in miniature, played on a loop beside the briefing: frames
        of (seconds, rows), each row a list of (text, colour) pieces. A colour
        can be a hex view style ("sel", "found"...), so bytes look as they do
        in the dump. It shows how, never where: nothing in it is an answer on
        this node."""
        return []

    def panel(self):
        """Side panel lines: (text, colour key) or (text, colour key, key to
        send when the line is clicked)."""
        return []

    def layers(self):
        return self.packet.layers if self.packet is not None else []

    # ---- tool hooks: return True if the tool did something
    def bruteforce(self):
        return False

    def snapshot(self):
        return False

    def scan(self):
        return False

    # ---- helpers
    def say(self, text, color="fg"):
        self.messages.append((text, color))

    def _mistake(self, text, severity=WRONG):
        self.mistakes += 1
        self.severity = severity
        self.say(text, "red")
        return "mistake"

    def _solve(self, text):
        self.solved = True
        self.say(text, "amber")
        return "solved"

    def _flash(self, indices, secs=2.5):
        for i in indices:
            self.flash[i] = secs

    def tick(self, dt):
        if self.flash:
            self.flash = {i: t - dt for i, t in self.flash.items() if t - dt > 0}


def apply_actions(puzzle, actions):
    """Feed a list of actions straight into a puzzle. Returns the results."""
    results = []
    for action in actions:
        op = action[0]
        if op == "click":
            results.append(puzzle.click(action[1]))
        elif op == "select":
            results.append(puzzle.select(action[1], action[2]))
        elif op == "move":
            results.append(puzzle.move(action[1], action[2]))
        elif op == "type":
            results.extend(puzzle.key(ch) for ch in action[1])
        elif op == "key":
            results.append(puzzle.key(action[1]))
        else:
            raise ValueError(action)
    return results
