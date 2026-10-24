"""REASSEMBLE: a stream arrived cut into segments, out of order. Each segment
starts with its sequence number. Drag each one to where its data belongs in
the stream: at offset seq - the stream's first seq. This is what TCP does with
every connection, and what Wireshark's "Follow TCP Stream" shows.

The dump is two parts: the stream at the top, starting at offset 0000, its
bytes empty (__) until filled; under it, one segment a row."""
import random

import sources
from packets import build_http_request

from .base import (BEAT, MODES_ALL, NEAR, REST, WILD, WRONG, Puzzle, at, cells, count, hexs, pointer, printable,
                   ramp, step)

EMPTY, VOID = "empty", "void"       # hex view styles: a stream byte still to fill, a cell with no byte at all


class Reassemble(Puzzle):
    kind = "REASSEMBLE"
    modes = MODES_ALL
    first = at(3)
    select_mode = "move"
    what = "TCP reassembly: put a stream's segments back in order by their sequence numbers."
    do = "Drag each segment to where its data goes."
    PAY = 1.35

    COLS = 16
    SEGMENTS = [(at(1), 3), (at(3, 4), 4), (at(4), 5), (at(5), 6)]      # the stream is cut into this many
    # sequence numbers: how many bytes they take, and whether the stream starts at seq 0
    SEQ = [(at(1), (1, True)), (at(3, 3), (1, False)), (at(4), (2, False)), (at(5), (4, False))]
    WRAP = at(5, 4)             # from here a 4-byte seq may run past FFFFFFFF and start again at 0
    DECOYS = [(at(1), 0), (at(3, 5), 1), (at(5), 2)]        # segments from outside the stream
    DUPES = [(at(1), 0), (at(4), 1)]                        # a segment sent twice
    OVERLAPS = [(at(1), 0), (at(5), 1)]                     # a resend that covers the end of one and start of the next
    DATA = [(at(1), (4, 8)), (at(3, 4), (3, 10)), (at(4), (3, 12))]     # bytes of data a segment
    TIME = [100, 95, 90, 82, 75, 68]        # seconds for as many segments as is usual at the level; more or fewer, more or less

    @classmethod
    def generate(cls, seed, source, level):
        rng = random.Random(seed)
        p = cls(seed, level)
        p.cols = cols = cls.COLS
        p.seqlen, zero = step(level, cls.SEQ)
        lo, hi = step(level, cls.DATA)
        hi = min(hi, cols - p.seqlen)
        sizes = [rng.randint(lo, hi) for _ in range(step(level, cls.SEGMENTS) + rng.choice([0, 0, 1]))]
        p.length = n = sum(sizes)
        p.stream = cls._stream(rng, source, level, n)

        # where the stream starts, and room either side of it for decoys
        p.mod = 1 << (8 * p.seqlen)
        if zero:
            p.isn = 0
        elif p.seqlen == 4 and level >= cls.WRAP and rng.random() < 0.4:
            p.isn = p.mod - rng.randint(4, n - 1)               # the stream wraps past FFFFFFFF
        else:
            p.isn = rng.randint(0x30, p.mod - n - 0x30)

        segs, at_ = [], 0           # (seq, data, real): real is False for a decoy
        for size in sizes:
            segs.append((at_, p.stream[at_:at_ + size], True))
            at_ += size
        for _ in range(step(level, cls.DUPES)):
            segs.append(rng.choice(segs[:len(sizes)]))
        for _ in range(step(level, cls.OVERLAPS)):
            i = rng.randrange(len(sizes) - 1)
            a, b = segs[i], segs[i + 1]
            start = rng.randint(a[0] + 1, a[0] + len(a[1]) - 1)
            end = min(rng.randint(b[0] + 1, b[0] + len(b[1])), start + cols - p.seqlen)
            segs.append((start, p.stream[start:end], True))
        for _ in range(step(level, cls.DECOYS)):
            size = rng.randint(lo, hi)
            # just before the stream, or just past its end: only the arithmetic tells
            off = -rng.randint(size, 0x24) if rng.random() < 0.5 else n + rng.randint(0, 0x20)
            segs.append((off, bytes(rng.getrandbits(8) for _ in range(size)), False))
        while True:
            rng.shuffle(segs)
            if [s[0] for s in segs] != sorted(s[0] for s in segs):
                break

        # the dump: the stream's rows, a gap row, then one segment a row
        p.top = (n + cols - 1) // cols + 1
        p.segs = []                 # (row start in the dump, seq, data, offset into the stream or None)
        for r, (off, data, real) in enumerate(segs):
            seq = (p.isn + off) % p.mod
            p.segs.append(((p.top + r) * cols, seq, bytes(data), off if real else None))
        p.data = bytearray((p.top + len(segs)) * cols)
        for start, seq, data, _ in p.segs:
            p.data[start:start + p.seqlen + len(data)] = seq.to_bytes(p.seqlen, "big") + data
        p.filled = bytearray(n)
        p.have = [False] * n
        p.placed = set()            # row starts of segments already dropped in
        # the moves that solve it: each of the original segments, as they come in the dump
        firsts, cut = [], 0
        for size in sizes:
            firsts.append((cut, size))
            cut += size
        originals = set(firsts)
        p.solution = [(start, off) for start, _, data, off in p.segs if (off, len(data)) in originals]
        seen = set()                # a dupe of an original is not needed twice
        p.solution = [s for s in p.solution if not (s[1] in seen or seen.add(s[1]))]
        usual = sum(step(level, t) for t in (cls.SEGMENTS, cls.DECOYS, cls.DUPES, cls.OVERLAPS))
        p.time_limit = round(ramp(level, cls.TIME) * (0.6 + 0.4 * len(p.segs) / usual))
        return p

    @staticmethod
    def _stream(rng, source, level, n):
        """n bytes of stream: random in RAW; in PROTOCOL and LIVE a TCP payload
        when one is long enough, else the text of an HTTP request."""
        if not source.has_packets:
            return bytes(source.buffer(n, rng, level=level))
        for _ in range(6):
            pkt = source.packet(rng, level, need=("TCP",))
            span = pkt.layer_range("TCP") if pkt is not None else None
            if span and len(pkt.raw) - span[1] >= n:
                return pkt.raw[span[1]:span[1] + n]
        text = build_http_request(rng.choice(["GET", "GET", "POST"]), rng.choice(sources.PATHS),
                                  rng.choice(sources.HOSTS), [("User-Agent", rng.choice(sources.AGENTS))])
        while len(text) < n:
            text += text
        return text[:n]

    # ---- checking
    def validate(self, answer):
        """answer: (row start of a segment, offset it is dropped at) pairs."""
        got, by = bytearray(self.length), {s[0]: s for s in self.segs}
        have = [False] * self.length
        for start, off in answer:
            _, _, data, right = by[start]
            if right is None or off != right:
                return False
            got[off:off + len(data)] = data
            for i in range(off, off + len(data)):
                have[i] = True
        return all(have) and bytes(got) == self.stream

    def solution_actions(self):
        return [("move", start, off) for start, off in self.solution]

    def offset(self, seq):
        """Where a seq goes in the stream: seq - the first seq, round the top for a seq that wrapped."""
        return (seq - self.isn) % self.mod

    def seg_at(self, idx):
        return next((s for s in self.segs if s[0] <= idx < s[0] + self.cols), None) if idx is not None else None

    # ---- input
    def move(self, src, dst):
        if self.solved:
            return None
        seg = self.seg_at(src)
        if seg is None or dst is None or not 0 <= dst < self.length:
            return None             # not a segment, or put back down outside the stream: nothing happens
        start, seq, data, right = seg
        if start in self.placed:
            self.say("that segment is already in", "dim")
            return None
        name = "seq %s" % self.seqhex(seq)
        if right is None:
            return self._mistake("%s is outside the stream, seq %s to %s" % (
                name, self.seqhex(self.isn), self.seqhex((self.isn + self.length - 1) % self.mod)))
        if dst != right:
            d = dst - right
            if abs(d) <= 2 or abs(d) == self.cols:
                severity = NEAR
            elif dst + len(data) > self.length:
                severity = WILD
            else:
                severity = WRONG
            return self._mistake("%s does not start at 0x%04X" % (name, dst), severity)
        self.placed.add(start)
        new = sum(not self.have[i] for i in range(dst, dst + len(data)))
        self.filled[dst:dst + len(data)] = data
        for i in range(dst, dst + len(data)):
            self.have[i] = True
        if all(self.have):
            text = printable(self.stream[:40], self.codepage)
            self.say("stream: %s%s" % (text, "..." if self.length > 40 else ""), "fg")
            return self._solve("stream reassembled")
        if not new:
            self.say("%s: all of it was in already, a resend" % name, "dim")
        else:
            self.say("%s -> 0x%04X, %s" % (name, dst, count(new, "new byte")), "fg")
        return "ok"

    def seqhex(self, seq):
        return "%0*X" % (2 * self.seqlen, seq)

    # ---- display
    def display(self):
        data = bytearray(self.data)
        data[:self.length] = self.filled
        ghost = self._ghost()
        if ghost:
            dst, seg = ghost
            part = seg[2][:self.length - dst]
            data[dst:dst + len(part)] = part
        return data

    def _ghost(self):
        """While a segment is dragged over the stream: (where it would land, the segment)."""
        if not self.drag or self.solved:
            return None
        seg = self.seg_at(self.drag[0])
        dst = self.drag[1]
        if seg is None or seg[0] in self.placed or dst is None or not 0 <= dst < self.length:
            return None
        return dst, seg

    def styles(self):
        st, cols = {}, self.cols
        for i in range(len(self.data)):
            if i < self.length:
                if not self.have[i]:
                    st[i] = EMPTY
            elif i < self.top * cols:
                st[i] = VOID
        lifted = self.seg_at(self.drag[0]) if self.drag and not self.solved else None
        for seg in self.segs:
            start, _, data, _ = seg
            used = self.seqlen + len(data)
            for i in range(start, start + cols):
                if i >= start + used:
                    st[i] = VOID
                elif start in self.placed:
                    st[i] = "dim"
                elif seg is lifted:
                    st[i] = "picked"
                elif i < start + self.seqlen:
                    st[i] = "band"
        ghost = self._ghost()
        if ghost:
            dst, seg = ghost
            for i in range(dst, min(self.length, dst + len(seg[2]))):
                st[i] = "sel"
        for i in self.flash:
            st[i] = "flash"
        return st

    def tasks(self):
        done = sum(self.have)
        return self._ordered(["Fill the stream from seq %s (%d/%d bytes)" % (
            self.seqhex(self.isn), done, self.length)], 0)

    def summary(self):
        return "a %d-byte stream in %s" % (self.length, count(len(self.segs), "segment"))

    def _fakes(self):
        return sum(s[3] is None for s in self.segs)

    def brief(self):
        rows = [("DO", self.do),
                ("STREAM", "%d bytes, from seq %s" % (self.length, self.seqhex(self.isn))),
                ("SEGMENTS", "%d, out of order; seq is the %s" % (
                    len(self.segs), "1st byte" if self.seqlen == 1 else "first %d bytes" % self.seqlen))]
        extra = []
        if self._fakes():
            extra.append("%d not in the stream" % self._fakes())
        if step(self.level, self.DUPES) or step(self.level, self.OVERLAPS):
            extra.append("some sent twice")
        if extra:
            rows.append(("WATCH", ", ".join(extra)))
        if self.isn + self.length > self.mod:
            rows.append(("WRAP", "seq runs past %s and on from 0" % ("FF" * self.seqlen)))
        return rows

    def example(self):
        """Two segments of "HELLO", dropped where their seq says."""
        stream, segs = b"HELLO", [(3, b"LO"), (0, b"HEL")]
        pad = "STREAM "
        frames, have = [], set()

        def line(ghost=None, done=False):
            data, styles = bytearray(stream), {}
            for i in range(len(stream)):
                if done:
                    styles[i] = "found"
                elif ghost and ghost[0] <= i < ghost[0] + len(ghost[1]):
                    data[i], styles[i] = ghost[1][i - ghost[0]], "sel"
                elif i not in have:
                    styles[i] = EMPTY
            pieces = cells(data, styles)
            out = [(pad, "dim")]
            for text, style in pieces:      # empty bytes read __
                if style == EMPTY:
                    text, style = " ".join("__" for _ in text.split(" ")), "dim"
                out.append((text, style))
            return out

        def under(i, note):
            return [(" " * len(pad) + pointer(i, note)[0][0], "tan")]

        for seq, data in segs:
            seg = bytes([seq]) + data
            row = [("SEG    ", "dim")] + cells(seg, {0: "band"})
            lifted = [("SEG    ", "dim")] + cells(seg, dict.fromkeys(range(len(seg)), "picked"))
            frames.append((BEAT, [line(), [], row, under(0, "grab seq %02X" % seq)]))
            frames.append((BEAT, [line((seq, data)), under(seq, "drop at %02X" % seq), lifted, []]))
            have.update(range(seq, seq + len(data)))
        frames.append((REST, [line(done=True), [], [], []]))
        return frames

    def panel(self):
        return []           # the first seq is in the task, and each segment's seq is tinted in the dump

    # ---- tools
    def _left(self):
        return [s for s in self.segs if s[3] is not None and s[0] not in self.placed
                and not all(self.have[s[3]:s[3] + len(s[2])])]

    def bruteforce(self):
        left = self._left()
        if self.solved or not left:
            return False
        start, seq, _, off = left[0]
        self.say("BRUTEFORCE: seq %s tried at every offset, it fits at 0x%04X" % (self.seqhex(seq), off), "tan")
        self.move(start, off)
        return True

    def scan(self):
        left = self._left()
        if self.solved or not left:
            return False
        start, seq, data, off = left[0]
        self._flash(list(range(start, start + self.seqlen)) + list(range(off, off + len(data))), 3.0)
        self.say("SCANNER: seq %s goes at 0x%04X" % (self.seqhex(seq), off), "tan")
        return True
