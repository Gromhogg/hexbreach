"""PAYLOAD: a breach. Pick bytes off a square grid, alternating row and
column, to spell the target sequences before the buffer fills. There are
three, each longer than the last, and they chain: the last byte of one is
the first byte of the next, and the buffer has room for little more than the
chain. The breach is rated by the deepest sequence uploaded (SHALLOW BREACH,
BREACH, DEEP BREACH) and pays by that rank."""
import random

from .base import BEAT, NEAR, REST, STEP, WILD, WRONG, Puzzle, PuzzleUnavailable, at, cells, count, hexs, ramp, step


class Payload(Puzzle):
    kind = "PAYLOAD"
    first = at(1, 3)
    what = "Payload assembly: pick bytes off a grid so that exact sequences land in a buffer."
    do = "Pick bytes off the grid to spell the sequences."
    PAY = 1.1

    SIZE = [(at(1), 5), (at(2), 6), (at(3, 4), 7), (at(5), 8)]      # the grid is SIZE by SIZE
    PALETTE = [(at(1), 5), (at(3), 6), (at(5), 7)]      # distinct byte values (RAW only)
    # the three sequences, shortest first; the rank is the deepest one uploaded
    RANKS = (("SHALLOW BREACH", 0.5), ("BREACH", 1.0), ("DEEP BREACH", 2.0))
    TARGETS = [(at(1), [2, 3, 4]), (at(2, 3), [2, 3, 5]), (at(3, 3), [3, 4, 5]),
               (at(4, 3), [3, 4, 6]), (at(5, 3), [3, 5, 6])]
    SLACK = [(at(1), 2), (at(2), 1), (at(3, 4), 0)]     # buffer cells beyond the chain
    TIME = [60, 55, 50, 46, 43, 40]

    @classmethod
    def generate(cls, seed, source, level):
        rng = random.Random(seed)
        p = cls(seed, level)
        size = p.cols = p.rows = step(level, cls.SIZE)
        data = bytearray(source.buffer(size * size, rng, palette=step(level, cls.PALETTE), level=level))
        while len(data) < size * size:
            data.append(rng.getrandbits(8))
        p.data = data
        lens = step(level, cls.TARGETS)
        waste = rng.randrange(2) if level >= 2 else 0     # a first pick that is part of nothing
        chain = sum(lens) - (len(lens) - 1)                # each sequence shares a byte with the next
        for _ in range(500):
            path = cls._random_path(rng, size, size, waste + chain)
            if path is not None:
                break
        else:
            raise PuzzleUnavailable("no route through the grid")
        p.targets, pos = [], waste
        for n in lens:
            p.targets.append(bytes(data[i] for i in path[pos:pos + n]))
            pos += n - 1
        p.buffer_size = len(path) + step(level, cls.SLACK)
        # with few distinct byte values the targets can complete before the
        # planned route ends; the known solution stops there
        for n in range(1, len(path) + 1):
            if all(p.done([(i, False) for i in path[:n]])):
                break
        p.solution = path[:n]
        p.luck = rng.uniform(0.85, 1.15)     # a little either way, which the pay makes up for
        p.time_limit = round(ramp(level, cls.TIME) * p.luck)
        p.picks = []            # (index, is bruteforce)
        p.wild_next = False
        return p

    @staticmethod
    def _random_path(rng, rows, cols, length):
        """A route of picks, or None when it boxed itself in."""
        r, c = 0, rng.randrange(cols)
        used = {(r, c)}
        path = [r * cols + c]
        for step in range(1, length):
            if step % 2:        # move within the column
                free = [x for x in range(rows) if (x, c) not in used]
            else:               # move within the row
                free = [x for x in range(cols) if (r, x) not in used]
            if not free:
                return None
            if step % 2:
                r = rng.choice(free)
            else:
                c = rng.choice(free)
            used.add((r, c))
            path.append(r * cols + c)
        return path

    def difficulty(self):
        d = 1.0 - 0.6 * (self.luck - 1)     # a short timer pays more
        return max(0.6, min(1.4, d))

    def ranks(self):
        return list(self.RANKS)

    # ---- rules
    def allowed(self, picks=None):
        """Indices that may be picked next."""
        picks = self.picks if picks is None else picks
        taken = {i for i, _ in picks}
        cols = self.cols
        if not picks:
            line = range(cols)
        else:
            r, c = divmod(picks[-1][0], cols)
            if len(picks) % 2:
                line = [x * cols + c for x in range(self.rows)]
            else:
                line = [r * cols + x for x in range(cols)]
        return [i for i in line if i not in taken]

    def _buffer(self, picks):
        return [None if wild else self.data[i] for i, wild in picks]

    @staticmethod
    def _contains(buf, target):
        n = len(target)
        return any(all(b is None or b == t for b, t in zip(buf[s:s + n], target))
                   for s in range(len(buf) - n + 1))

    def done(self, picks=None):
        buf = self._buffer(self.picks if picks is None else picks)
        return [self._contains(buf, t) for t in self.targets]

    def reached(self, picks=None):
        """The rank earned so far: index of the deepest sequence in the buffer, or -1."""
        return max((i for i, ok in enumerate(self.done(picks)) if ok), default=-1)

    def next_byte(self):
        """The byte the first sequence not yet spelled needs next. The end of
        the buffer counts towards it: the last byte of one sequence is the
        first byte of the next. None when all are spelled."""
        target = next((t for t, ok in zip(self.targets, self.done()) if not ok), None)
        if target is None:
            return None
        buf = self._buffer(self.picks)
        held = next(n for n in range(min(len(buf), len(target) - 1), -1, -1)
                    if all(b is None or b == t for b, t in zip(buf[len(buf) - n:], target)))
        return target[held]

    def validate(self, answer):
        picks = []
        for idx in answer:
            if idx not in self.allowed(picks) or len(picks) >= self.buffer_size:
                return False
            picks.append((idx, False))
        return all(self.done(picks))

    def solution_actions(self):
        return [("click", i) for i in self.solution]

    # ---- input
    def click(self, idx):
        if self.solved or idx >= len(self.data):
            return None
        if idx not in self.allowed():
            if any(i == idx for i, _ in self.picks):
                self.say("already in the buffer", "dim")
            else:
                self.say("out of line: pick from the highlighted %s" % self._axis_name(), "dim")
            return None
        self.picks.append((idx, self.wild_next))
        self.wild_next = False
        if all(self.done()):
            return self._upload()
        if len(self.picks) >= self.buffer_size or not self.allowed():
            if self.reached() >= 0:
                return self._upload()       # the buffer is full: the breach ends with what is in it
            severity = self.judge()
            self.picks = []
            return self._mistake("BUFFER FULL with nothing uploaded: flushed, start again from the top row",
                                 severity)
        return "ok"

    def key(self, k):
        if k != "enter" or self.solved:
            return None
        if self.reached() < 0:
            self.say("nothing to upload yet", "dim")
            return None
        return self._upload()

    def _upload(self):
        """The breach ends: rated by the deepest sequence in the buffer."""
        self.rank = self.RANKS[self.reached()]
        return self._solve("%s: %d of %d sequences uploaded" % (self.rank[0], sum(self.done()), len(self.targets)))

    def judge(self):
        """How bad a wasted buffer is. NEAR: a byte short of a sequence of three
        or more. WILD: it did not hold so much as half of any sequence."""
        buf = self._buffer(self.picks)

        def held(t, n):
            """n bytes of t, in a row, are in the buffer."""
            return any(self._contains(buf, t[s:s + n]) for s in range(len(t) - n + 1))

        if any(len(t) >= 3 and held(t, len(t) - 1) for t in self.targets):
            return NEAR
        if any(held(t, (len(t) + 1) // 2) for t in self.targets):
            return WRONG
        return WILD

    def _axis_name(self):
        if not self.picks:
            return "top row"
        r, c = divmod(self.picks[-1][0], self.cols)
        return "column %02X" % c if len(self.picks) % 2 else "row %04X" % (r * self.cols)

    # ---- display
    def styles(self):
        st = {i: "active" for i in self.allowed()} if not self.solved else {}
        for i, wild in self.picks:
            st[i] = "picked"
        for i in self.flash:
            st[i] = "flash"
        return st

    def summary(self):
        return "%s to chain on a %d by %d grid, in a buffer of %d" % (
            count(len(self.targets), "sequence"), self.rows, self.cols, self.buffer_size)

    def tasks(self):
        """One step per sequence. Which line to pick from is not said: the dump only allows that line anyway."""
        ok = self.done()
        now = ok.index(False) if False in ok else len(ok)
        return [("Spell " + hexs(t), "done" if self.solved or ok[i] else "now" if i == now else "todo")
                for i, t in enumerate(self.targets)]

    def brief(self):
        rows = [("DO", self.do)]
        rows += [(name.split()[0], hexs(t)) for (name, _), t in zip(self.RANKS, self.targets)]
        rows.append(("BUFFER", "%d picks; the three chain, last byte to first" % self.buffer_size))
        return rows

    def example(self):
        want = self.targets[0][:3]
        route = [(0, 1), (2, 1), (2, 3)][:len(want)]        # top row, then down its column, then along that row
        other = [b for b in b"\xe9\x7a\xbd\x55\xff\x1c\x3e\xa2\x0b" if b not in want]
        grid = [bytearray(other[(4 * r + c) % len(other)] for c in range(4)) for r in range(3)]
        for (r, c), b in zip(route, want):
            grid[r][c] = b

        def frame(secs, done, cursor=None):
            """With this many bytes picked, and the mouse on the next."""
            if done == 0:
                line = [(0, c) for c in range(4)]
            elif done % 2:
                line = [(r, route[done - 1][1]) for r in range(3)]
            else:
                line = [(route[done - 1][0], c) for c in range(4)]
            style = dict.fromkeys(line if done < len(route) else [], "active")
            style.update(dict.fromkeys(route[:done], "picked"))
            if cursor is not None:
                style[cursor] = "sel"
            rows = [cells(grid[r], {c: s for (at_r, c), s in style.items() if at_r == r}) for r in range(3)]
            buffer = ["%02X" % b for b in want[:done]] + ["__"] * (len(want) - done)
            return secs, rows + [[], [("BUFFER  " + " ".join(buffer), "fg")]]

        frames = []
        for done, cell in enumerate(route):
            frames += [frame(BEAT, done), frame(2 * STEP, done, cell)]
        return frames + [frame(REST, len(route))]

    def panel(self):
        buf = self._buffer(self.picks)
        cells = ["**" if b is None else "%02X" % b for b in buf] + ["__"] * (self.buffer_size - len(buf))
        lines = [("BUFFER %d/%d" % (len(buf), self.buffer_size), "amber"), ("  " + " ".join(cells), "fg"),
                 ("", "fg"), ("NEXT PICK: %s" % self._axis_name().upper(), "amber")]
        need = None if self.solved else self.next_byte()
        if need is not None:
            lines.append(("NEXT BYTE: %02X" % need, "amber"))
        lines += [("", "fg"), ("SEQUENCES", "amber")]
        width = max(len(t) for t in self.targets) * 3
        for (name, _), t, ok in zip(self.RANKS, self.targets, self.done()):
            lines.append(("  [%s] %-*s %s" % ("x" if ok else " ", width, hexs(t), name), "dim" if ok else "fg"))
        if self.wild_next:
            lines += [("", "fg"), ("BRUTEFORCE armed: next pick matches anything", "tan")]
        if self.reached() >= 0 and not self.solved:
            lines += [("", "fg"), ("[ENTER] upload now: %s" % self.RANKS[self.reached()][0], "tan", "enter")]
        return lines

    # ---- tools
    def bruteforce(self):
        if self.wild_next or self.solved:
            return False
        self.wild_next = True
        self.say("BRUTEFORCE armed: your next pick matches any byte", "tan")
        return True

    def snapshot(self):
        if not self.picks or self.solved:
            return False
        self.picks.pop()
        self.say("SNAPSHOT: last pick undone", "tan")
        return True

    def scan(self):
        if self.solved:
            return False
        mine = [i for i, _ in self.picks]
        if mine != self.solution[:len(mine)]:
            self.picks = []
            self.say("SCANNER: buffer cleared, known-good route starts here", "tan")
            self._flash([self.solution[0]])
        else:
            self.say("SCANNER: next byte on a known-good route", "tan")
            self._flash([self.solution[len(mine)]])
        return True
