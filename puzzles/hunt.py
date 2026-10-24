"""HUNT: find every occurrence of a byte pattern in a large dump. Some near-copies
(lookalikes) differ only in a byte that prints as "." either way, so the ASCII
pane shows where to look but only the hex says which copies are real."""
import random

from .base import (BEAT, NEAR, REST, STEP, WILD, WRONG, Puzzle, PuzzleUnavailable, at, cells, count, hexs, pick_cols,
                   pointer, printable, ramp, spread, step, walk)


def find_all(data, pattern):
    out, i = [], data.find(pattern)
    while i >= 0:
        out.append(i)
        i = data.find(pattern, i + 1)
    return out


def _dot(b):
    """Shows as "." in the ASCII pane."""
    return not 32 <= b < 127


def _spaced(positions, n):
    return all(b - a >= n for a, b in zip(positions, positions[1:]))


class Hunt(Puzzle):
    kind = "HUNT"
    what = "Pattern search: find every copy of a short byte sequence in a dump."
    do = "Click every copy of the pattern."
    PAY = 0.8

    WINDOW = 24                                 # rows of dump on screen at once
    SIZE = [96, 176, 256, 320, 384, 448]        # bytes of dump; more than 384 has to be scrolled
    LENGTH = [(at(1), 4), (at(2, 4), 3), (at(4, 4), 2)]             # short patterns are harder to spot
    COUNT = [(at(1), 2), (at(1, 4), 3), (at(3), 4), (at(5), 5)]     # occurrences to find
    LOOKALIKES = [(at(1), 1), (at(2), 2), (at(4), 3)]   # near-copies that only the hex tells apart
    TIME = [60, 52, 46, 42, 38, 35]

    @classmethod
    def generate(cls, seed, source, level):
        rng = random.Random(seed)
        p = cls(seed, level)
        p.cols = pick_cols(rng)
        size = spread(rng, ramp(level, cls.SIZE), p.cols)
        # the counts wander a little either side of the level's: no two nodes alike
        n = step(level, cls.LENGTH)
        k = max(2, step(level, cls.COUNT) + rng.choice([-1, 0, 0, 1]))
        fakes = max(0, step(level, cls.LOOKALIKES) + rng.choice([-1, 0, 1]))
        base = bytearray(source.buffer(size, rng, level=level))
        while len(base) < size:
            base.append(rng.getrandbits(8))
        for _ in range(20):
            found = cls._natural(base, n, k, rng) or cls._plant(base, n, k, rng)
            if found is None:
                raise PuzzleUnavailable("could not place a pattern")
            found = (bytearray(found[0]),) + found[1:]      # lookalikes go into a copy: base stays clean for a retry
            looks = cls._lookalikes(rng, *found, fakes)
            if looks is not None:
                break
        else:
            raise PuzzleUnavailable("could not place lookalikes")
        p.data, p.pattern, p.solution = found
        p.lookalikes = looks        # (start, index of the byte that differs)
        # more to search, more time; then a little luck either way, which the pay makes up for
        work = 0.5 * len(p.data) / ramp(level, cls.SIZE) + 0.5 * len(p.solution) / step(level, cls.COUNT)
        p.luck = rng.uniform(0.85, 1.15)
        p.time_limit = round(ramp(level, cls.TIME) * (0.75 + 0.25 * work) * p.luck)
        p.found = set()
        return p

    @staticmethod
    def _natural(data, n, k, rng):
        """A pattern that already repeats about k times, e.g. an address that
        shows up in every packet of a conversation."""
        seen = {}
        for i in range(len(data) - n + 1):
            seen.setdefault(bytes(data[i:i + n]), []).append(i)
        cands = [(pat, pos) for pat, pos in seen.items()
                 if max(2, k - 1) <= len(pos) <= k + 1 and len(set(pat)) > 1 and _spaced(pos, n)
                 and any(map(_dot, pat))]
        if not cands:
            return None
        cands.sort()
        pat, pos = rng.choice(cands)
        return data, pat, pos

    @staticmethod
    def _plant(base, n, k, rng):
        for attempt in range(200):
            data = bytearray(base)
            if attempt < 100:       # prefer a pattern that looks native to the dump
                at = rng.randrange(len(data) - n + 1)
                pat = bytes(data[at:at + n])
            else:
                pat = bytes(rng.getrandbits(8) for _ in range(n))
            if len(set(pat)) < 2 or not any(map(_dot, pat)):
                continue
            pos = find_all(data, pat)
            if len(pos) > k or not _spaced(pos, n):
                continue
            for _ in range(400):
                if len(pos) >= k:
                    break
                at = rng.randrange(len(data) - n + 1)
                if all(abs(at - q) >= n + 1 for q in pos):
                    data[at:at + n] = pat
                    pos = find_all(data, pat)
            if len(pos) == k and _spaced(pos, n):
                return data, pat, pos
        return None

    @staticmethod
    def _lookalikes(rng, data, pat, pos, count):
        """Plant count near-copies of pat in data, each with one "." byte
        swapped for another "." byte. Returns their (start, index), or None."""
        n, out = len(pat), []
        dots = [j for j in range(n) if _dot(pat[j])]
        for _ in range(400):
            if len(out) == count:
                break
            at = rng.randrange(len(data) - n + 1)
            if any(abs(at - q) < n + 2 for q in pos + [s for s, _ in out]):
                continue
            j = rng.choice(dots)
            v = rng.choice([b for b in list(range(1, 32)) + list(range(127, 256)) if b != pat[j]])
            data[at:at + n] = pat[:j] + bytes([v]) + pat[j + 1:]
            out.append((at, j))
        if len(out) < count or find_all(data, pat) != pos:
            return None
        return sorted(out)

    def difficulty(self):
        d = 1.0 + 0.2 * (len(self.data) / ramp(self.level, self.SIZE) - 1)
        d += 0.1 * (len(self.solution) - step(self.level, self.COUNT))
        d += 0.1 * (len(self.lookalikes) - step(self.level, self.LOOKALIKES))
        d -= 0.6 * (self.luck - 1)          # a short timer pays more
        # letters stand out in the ASCII pane; dots do not
        d -= 0.4 * (sum(not _dot(b) for b in self.pattern) / len(self.pattern) - 0.5)
        return max(0.6, min(1.4, d))

    def validate(self, answer):
        return sorted(set(answer)) == self.solution == find_all(self.data, self.pattern)

    def solution_actions(self):
        return [("click", i) for i in self.solution]

    def click(self, idx):
        if self.solved:
            return None
        n = len(self.pattern)
        for start in self.solution:
            if start <= idx < start + n:
                if start in self.found:
                    return None
                self.found.add(start)
                if len(self.found) == len(self.solution):
                    return self._solve("pattern fully mapped")
                self.say("match at 0x%04X  (%d/%d)" % (start, len(self.found), len(self.solution)))
                return "ok"
        for start, j in self.lookalikes:
            if start <= idx < start + n:
                return self._mistake("lookalike: byte %d is %02X, not %02X" % (
                    j + 1, self.data[start + j], self.pattern[j]), NEAR)
        severity = self.judge(idx)
        if severity == NEAR:
            return self._mistake("0x%04X: close, but that is not the pattern" % idx, NEAR)
        if severity == WILD:
            return self._mistake("0x%04X: %02X is nowhere in the pattern" % (idx, self.data[idx]), WILD)
        return self._mistake("0x%04X is not part of the pattern" % idx)

    def judge(self, idx):
        """How bad a wrong click is. NEAR: right beside an occurrence, or on
        bytes that match at least half the pattern. WILD: on a byte value the
        pattern does not even contain."""
        n, pat, data = len(self.pattern), self.pattern, self.data
        if any(idx in (start - 1, start + n) for start in self.solution):
            return NEAR
        best = max(sum(data[start + j] == pat[j] for j in range(n))
                   for start in range(max(0, idx - n + 1), min(idx, len(data) - n) + 1))
        if best * 2 >= n:
            return NEAR
        return WRONG if data[idx] in pat else WILD

    def styles(self):
        n = len(self.pattern)
        st = {start + j: "found" for start in self.found for j in range(n)}
        for i in self.flash:
            st.setdefault(i, "flash")
        return st

    def summary(self):
        return "the pattern %s, %s in %d bytes" % (hexs(self.pattern), count(len(self.solution), "time"),
                                                   len(self.data))

    def tasks(self):
        return self._ordered(["Find %s (%d/%d)" % (hexs(self.pattern), len(self.found), len(self.solution))], 0)

    def brief(self):
        size = "%d bytes" % len(self.data) + (", scroll to see it all" if len(self.data) > self.WINDOW * self.cols else "")
        rows = [("DO", self.do), ("PATTERN", hexs(self.pattern)),
                ("COPIES", "%d, in %s" % (len(self.solution), size))]
        if self.lookalikes:
            rows.append(("FAKES", "%d: %s" % (len(self.lookalikes), self._fakes_note())))
        return rows

    def _fakes_note(self):
        """How a fake is told from a copy. With CODEPAGE the ASCII pane tells them apart too."""
        return "one byte off the pattern" if self.codepage else "same ASCII, check the hex"

    def example(self):
        n = len(self.pattern)
        line, copies = b"\x7f" + self.pattern + b"\x09\x3c" + self.pattern, (1, n + 3)
        frames, found, here = [], [], 0

        def frame(secs, mouse):
            styles = {start + j: "found" for start in found for j in range(n)}
            frames.append((secs, [cells(line, styles), mouse, [("FOUND %d/%d" % (len(found), len(copies)), "fg")]]))

        frame(BEAT, pointer(here))
        for start in copies:
            for here in walk(here, start):
                frame(STEP, pointer(here))
            found.append(start)
            frame(BEAT, pointer(here, "click"))
        frame(REST, [])
        return frames

    def panel(self):
        return [("PATTERN", "amber"), ("  " + hexs(self.pattern), "fg"),
                ("  ascii: %s" % printable(self.pattern, self.codepage), "dim"), ("", "fg"),
                ("FOUND %d/%d" % (len(self.found), len(self.solution)), "amber"), ("", "fg"),
                ("%s: %s" % (count(len(self.lookalikes), "fake"), self._fakes_note()), "dim"),
                ("dump is 0x%04X bytes" % len(self.data), "dim"),
                ("wheel / arrows / PgUp PgDn to scroll", "dim")]

    def scan(self):
        left = [s for s in self.solution if s not in self.found]
        if self.solved or not left:
            return False
        start = left[0]
        self._flash(range(start, start + len(self.pattern)), 3.0)
        self.say("SCANNER: echo at 0x%04X" % start, "tan")
        return True
