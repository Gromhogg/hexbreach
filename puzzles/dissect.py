"""DISSECT: select the bytes that hold a named header field."""
import random
import textwrap

from packets import FIELD_INFO

from .base import (BEAT, MODES_PACKET, NEAR, REST, STEP, WILD, WRONG, Puzzle, PuzzleUnavailable, at, cells, count,
                   pointer, ramp, step, walk)

# layer -> the level from which its fields are asked about
LAYER_FROM = {"Ethernet": at(1), "IPv4": at(1), "IPv6": at(1), "TCP": at(2), "UDP": at(2),
              "DNS": at(3), "HTTP": at(4)}
# How long the panel keeps helping with a layer, in subnets since it came in:
# first it gives the field's offset and size, then only its size, then nothing.
HELP_OFFSET = 1.0
HELP_SIZE = 2.0
# what a layer's bytes are called in the help line
UNIT = {"DNS": "message", "HTTP": "message"}


class Dissect(Puzzle):
    kind = "DISSECT"
    modes = MODES_PACKET
    select_mode = "drag"
    what = "Packet dissection: pick out header fields in a captured frame."
    do = "Drag over the bytes of each field asked for."
    # fields to show the job with: (label, the bytes before it, its own, the bytes after)
    EXAMPLES = (("EtherType", "3A 9C", "08 00", "45 00"), ("Time to Live", "40 00", "40", "06 B1"))
    PAY = 1.0

    ROUNDS = [(at(1), 2), (at(1, 4), 3), (at(3), 4), (at(5), 5)]     # fields to find
    TIME = [80, 66, 58, 54, 50, 46]

    @classmethod
    def generate(cls, seed, source, level):
        rng = random.Random(seed)
        p = cls(seed, level)
        rounds = step(level, cls.ROUNDS)
        allowed = {layer for layer, start in LAYER_FROM.items() if start <= level}
        best = None
        for _ in range(12):
            pkt = source.packet(rng, level)
            if pkt is None:
                raise PuzzleUnavailable("DISSECT needs packets")
            cands = [f for f in pkt.fields.values() if f.name in FIELD_INFO and f.layer in allowed]
            if best is None or len(cands) > len(best[1]):
                best = (pkt, cands)
            if len(cands) >= rounds:
                break
        pkt, cands = best
        if not cands:
            raise PuzzleUnavailable("no dissectable fields")
        rounds = min(rounds, len(cands))
        # always ask about the deepest layer present, that is where the new material is
        deepest = cands[-1].layer
        deep = [f for f in cands if f.layer == deepest]
        first = rng.choice(deep)
        rest = rng.sample([f for f in cands if f is not first], rounds - 1)
        p.fields = rest + [first]
        rng.shuffle(p.fields)
        p.packet = pkt
        p.data = bytearray(pkt.raw)
        p.solution = [(f.start, f.end - 1) for f in p.fields]
        p.time_limit = round(ramp(level, cls.TIME))
        p.round = 0
        return p

    def validate(self, answer):
        return [tuple(a) for a in answer] == self.solution

    def solution_actions(self):
        return [("select", lo, hi) for lo, hi in self.solution]

    def current(self):
        return self.fields[self.round] if self.round < len(self.fields) else None

    def select(self, lo, hi):
        if self.solved:
            return None
        f = self.current()
        if (lo, hi) == (f.start, f.end - 1):
            self.learned.append(("field", f.name, f.value))
            self.say("%s > %s = %s" % (f.layer, f.label, f.value), "fg")
            self.round += 1
            if self.round == len(self.fields):
                return self._solve("frame dissected")
            return "ok"
        # say what they actually grabbed: a wrong answer still teaches something
        severity = self.judge(f, lo, hi)
        other = self.packet.field_at(lo)
        if other is not None and (lo, hi) == (other.start, other.end - 1):
            return self._mistake("that is %s > %s" % (other.layer, other.label), severity)
        if f.start <= lo and hi < f.end:
            return self._mistake("right place, but %s is %d byte(s) long" % (f.label, f.end - f.start), severity)
        if severity == NEAR:
            return self._mistake("close: that overlaps %s but is not exactly it" % f.label, severity)
        return self._mistake("0x%04X-0x%04X is not %s" % (lo, hi, f.label), severity)

    def judge(self, f, lo, hi):
        """How bad a wrong selection is. NEAR: it overlaps the field (right
        place, wrong edges). WILD: it is not even in the field's header."""
        if lo < f.end and hi >= f.start:
            return NEAR
        span = self.packet.layer_range(f.layer)
        return WRONG if span and span[0] <= lo < span[1] else WILD

    def click(self, idx):
        return self.select(idx, idx)

    def help_for(self, f):
        """Panel lines that say where a field is, while its layer is still new."""
        span = self.packet.layer_range(f.layer)
        age = self.level - LAYER_FROM.get(f.layer, 0)
        if span is None or age >= HELP_SIZE:
            return []
        size = f.end - f.start
        size = "%d byte%s" % (size, "" if size == 1 else "s")
        lines = ["%s %s starts at 0x%04X" % (f.layer, UNIT.get(f.layer, "header"), span[0])]
        if age < HELP_OFFSET:
            lines.append("field is at +0x%02X, %s" % (f.start - span[0], size))
        else:
            lines.append("field is %s long" % size)
        return lines

    def tasks(self):
        # always "drag", even over a 1-byte field: "click" would give away the size the help withholds
        return self._ordered(["Drag across %s > %s" % (f.layer, f.label) for f in self.fields], self.round)

    def _stack(self):
        return " > ".join(name for name, _, _ in self.packet.layers)

    def summary(self):
        return "%s to pick out of a %d-byte frame (%s)" % (count(len(self.fields), "field"), len(self.data),
                                                         self._stack())

    def brief(self):
        asked = [name for name, _, _ in self.packet.layers if any(f.layer == name for f in self.fields)]
        new = [name for name in asked if self.level - LAYER_FROM.get(name, 0) < HELP_SIZE]
        rows = [("DO", self.do), ("FRAME", "%s, %d bytes" % (self._stack(), len(self.data))),
                ("FIELDS", "%d, one at a time" % len(self.fields))]
        if new:
            rows.append(("HELP", "the panel says where %s fields are" % " and ".join(new)))
        return rows

    def example(self):
        asked = {f.label for f in self.fields}
        label, before, field, after = next((e for e in self.EXAMPLES if e[0] not in asked), self.EXAMPLES[0])
        before, field, after = (bytes.fromhex(s) for s in (before, field, after))
        line, lo, hi = before + field + after, len(before), len(before) + len(field) - 1
        ask, plain = [("FIND %s" % label, "amber")], cells(line)
        frames = [(BEAT, [ask, plain, pointer(0)])]
        frames += [(STEP, [ask, plain, pointer(i)]) for i in walk(0, lo)]
        for i in range(lo, hi + 1):         # the button goes down on the first byte and comes up on the last
            dragged = cells(line, dict.fromkeys(range(lo, i + 1), "sel"))
            frames.append((BEAT, [ask, dragged, pointer(i, "drag" if hi > lo else "click")]))
        frames.append((REST, [ask, cells(line, dict.fromkeys(range(lo, hi + 1), "found")), []]))
        return frames

    def styles(self):
        st = {}
        for f in self.fields[:self.round]:
            for i in range(f.start, f.end):
                st[i] = "found"
        for i in self.flash:
            st.setdefault(i, "flash")
        return st

    def panel(self):
        lines = [("FRAME: %d bytes" % len(self.data), "amber"), ("", "fg")]
        f = self.current()
        if f is not None:
            lines.append(("FIND", "amber"))
            lines += [("  " + row, "tan") for row in textwrap.wrap("%s > %s" % (f.layer, f.label), 38)]
            lines += [("  " + row, "dim") for row in self.help_for(f)]
            lines.append(("", "fg"))
        lines.append(("DISSECTED", "amber"))
        for g in self.fields[:self.round]:
            lines.append(("  0x%04X %s" % (g.start, g.label), "fg"))
            lines.append(("         = %s" % g.value[:30], "dim"))
        if self.solved:
            lines += [("", "fg")] + [(row, "dim") for row in textwrap.wrap(self.packet.summary(), 40)]
        return lines

    def scan(self):
        f = self.current()
        if f is None:
            return False
        rng = self.packet.layer_range(f.layer)
        if rng is None:
            return False
        self._flash(range(rng[0], rng[1]), 3.0)
        self.say("SCANNER: the %s %s is 0x%04X-0x%04X" % (f.layer, UNIT.get(f.layer, "header"), rng[0], rng[1] - 1),
                 "tan")
        return True
