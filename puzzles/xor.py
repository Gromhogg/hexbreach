"""XOR: the dump is XORed with a short repeating key. A few plaintext bytes are
known; recover the key (a known-plaintext attack). A key byte that has to be
worked out is typed as its eight bits; one that shows through, as two hex digits.
Over zero padding the key repeats in plain sight, and that pattern has to be
found first: nothing marks it. Now and then a dump is encrypted twice, and the
first key uncovers the second."""
import random
from types import SimpleNamespace

from .base import (BEAT, HEX_DIGITS, NEAR, REST, STEP, WIDTHS, WILD, WRONG, Puzzle, at, cells, count, hexs,
                   pointer, printable, ramp, spread, step, walk)

MARKERS = [b"root:x:0", b"PASSWORD", b"SSH-2.0-", b"<config>", b"username", b"BEGIN RS", b"ACCESS: "]


def xor_bytes(data, key, lo=0, hi=None):
    """data, with the bytes from lo up to hi XORed with the repeating key. The
    key lines up with the dump's offsets, wherever the span starts."""
    out, n = bytearray(data), len(key)
    for i in range(lo, len(out) if hi is None else hi):
        out[i] ^= key[i % n]
    return out


class Xor(Puzzle):
    kind = "XOR"
    first = at(2)
    what = "Known-plaintext attack: recover the key a dump was XORed with."
    do = "Work out the key and type it."
    PAY = 1.3
    own_levels = True

    # XOR has four levels of its own, climbed one solved XOR at a time: a run's
    # first XOR is level 1, its second 2, its third 3, and each one after that
    # is 3 or 4. RAW, by level: (key bytes it may have, the known plaintext is
    # text). Over zeros the key shows through; over text each key byte has to
    # be worked out.
    LEVELS = (((1,), False), ((2, 3), False), ((1,), True), ((2,), True))
    # zero padding is as long as the key, a few times over: (fewest, most) by key bytes.
    # So the pattern to find is 4 to 8 bytes of a 1-byte key, 6 to 10 of a 2-byte, 9 or 12 of a 3-byte.
    REPEATS = {1: (4, 8), 2: (3, 5), 3: (3, 4)}
    # a packet's known bytes are its own (08 00 45 00), so there a level is a key length
    PACKET_KEYS = (1, 2, 3, 4)
    # with no run to ask (practice): the XORs a run has usually solved by a level
    USUAL = [(at(1), 0), (at(2, 4), 1), (at(3), 2), (at(4), 3)]
    # A double XOR, now and then once a run has climbed the three steps: a block
    # of the dump is encrypted with one key, then all of it with another. The
    # first key found uncovers the known bytes of the second. Each key has an
    # XOR level of its own, any of the four; both are level 4 only from the
    # final subnet. Each key is 1 or 2 bytes: a packet has two known bytes for
    # each, and the steps for two longer keys would not fit the list.
    DOUBLE = 0.2                # the chance of one
    DOUBLE_TOP = at(5)          # both keys can be level 4 from here on
    DOUBLE_TIME = 1.5           # two keys take longer
    DOUBLE_PAY = 1.5            # and pay more
    SIZE = [96, 128, 160, 192, 208, 224]        # RAW only; packet modes encrypt one frame
    TIME = [110, 100, 92, 85, 80, 75]

    @classmethod
    def generate(cls, seed, source, level, solved=None):
        rng = random.Random(seed)
        p = cls(seed, level)
        if solved is None:
            solved = step(level, cls.USUAL)
        pkt = source.packet(rng, level, need=("Ethernet", "IPv4"))
        if pkt is not None and len(pkt.raw) < 16:
            pkt = None
        top = len(cls.LEVELS)
        if solved < 3:
            levels = [solved + 1]
        elif rng.random() >= cls.DOUBLE:
            levels = [rng.choice((3, 4))]
        else:
            levels = [rng.randint(1, 2 if pkt else top) for _ in range(2)]
            if levels == [top, top] and level < cls.DOUBLE_TOP:
                levels[rng.randrange(2)] = rng.randint(1, top - 1)
        # for each key: (key bytes, where its known bytes are, how many, what they are, the bytes it covers,
        # they are a pattern to find)
        if pkt is not None:
            # every IPv4-over-Ethernet frame gives away the bytes at 0x0C
            plain = bytearray(pkt.raw[:512])
            p.packet = pkt
            if len(levels) == 1:
                specs = [(cls.PACKET_KEYS[levels[0] - 1], 12, 4, "EtherType + start of the IPv4 header",
                          (0, len(plain)), False)]
            else:       # the IPv4 packet is the block: the frame's key gives the EtherType, the block's the header
                specs = [(levels[0], 12, 2, "EtherType", (0, len(plain)), False),
                         (levels[1], 14, 2, "start of the IPv4 header", (14, len(plain)), False)]
        else:
            # what each key's known bytes are: a text, or zero padding the key repeats over
            known, used = [], []
            for lv in levels:
                sizes, text = cls.LEVELS[lv - 1]
                n = rng.choice(sizes if len(levels) == 1 else [z for z in sizes if z <= 2])
                if text:
                    marker = rng.choice([m for m in MARKERS if m not in used])
                    used.append(marker)
                    known.append((n, marker, 'the text "%s"' % printable(marker)))
                else:
                    known.append((n, bytes(n * rng.randint(*cls.REPEATS[n])), "zero padding"))
            # rows wide enough to hold them whole
            p.cols = rng.choice([w for w in WIDTHS if w >= max(len(marker) for _, marker, _ in known)])
            size = spread(rng, ramp(level, cls.SIZE), p.cols)
            plain = bytearray(source.buffer(size, rng, level=level))
            while len(plain) < size:
                plain.append(rng.getrandbits(8))
            rooms = [(0, size)]
            if len(levels) > 1:     # the block is the top or the bottom half; the first key's known bytes, in the other
                half = size // p.cols // 2 * p.cols
                rooms = [(0, half), (half, size)]
                rng.shuffle(rooms)
            specs = []
            for k, ((lo, hi), (n, marker, why)) in enumerate(zip(rooms, known)):
                off = _place(rng, lo, hi, p.cols, len(marker), n)
                plain[off:off + len(marker)] = marker
                # over zeros the key repeats for all to see: the whole of that pattern, and it is to be found
                text = any(marker)
                specs.append((n, off, 4 if text else len(marker), why, (lo, hi) if k else (0, size), not text))
        # the last key to be found went on first: work back from the plaintext
        p.stages, data, under = [], plain, None
        for lv, (n, off, size, why, span, find) in reversed(list(zip(levels, specs))):
            key = _key(rng, n, under)
            # the known byte each key byte is worked out from: one that is 00
            # when there is one, since the key shows through it
            known = []
            for i in range(n):
                lined = [off + j for j in range(size) if j % n == i]
                known.append(next((o for o in lined if data[o] == 0), lined[0]))
            cipher = xor_bytes(data, key, *span)
            p.stages.insert(0, SimpleNamespace(
                level=lv, key=key, span=span, plain=data, cipher=cipher, off=off, why=why, known=known, find=find,
                hint=bytes(data[off:off + size]), widths=[8 if data[o] else 2 for o in known]))
            data, under = cipher, key
        p.time_limit = round(ramp(level, cls.TIME) * (cls.DOUBLE_TIME if len(levels) > 1 else 1))
        if len(levels) > 1:
            p.do = "Work out two keys, one after the other."
        p._enter(0)
        return p

    def _enter(self, k):
        """Make key k the one being worked on: the first, or the one it uncovers."""
        layer = self.stages[k]
        self.stage = k
        self.plain, self.cipher, self.span = layer.plain, layer.cipher, layer.span
        self.data = self.cipher
        self.solution, self.keylen, self.xor_level = layer.key, len(layer.key), layer.level
        self.hint_off, self.hint, self.hint_why = layer.off, layer.hint, layer.why
        self.known = layer.known
        self.widths = layer.widths      # what each key byte is typed as: 8 bits worked out, or 2 hex digits read off
        self.found = not layer.find     # the known bytes are marked: at once, or when their pattern is found
        self.flash = {}
        self.locked = {}                # key index -> byte revealed by a tool
        self.typed = ""                 # what has been typed for the remaining key bytes, in order: bits or hex digits

    @property
    def double(self):
        return len(self.stages) > 1

    def difficulty(self):
        return self.DOUBLE_PAY if self.double else 1.0

    def validate(self, answer):
        answer = bytes(answer)
        return len(answer) > 0 and xor_bytes(self.cipher, answer, *self.span) == self.plain

    def solution_actions(self):
        actions = [] if self.found else [("click", self.hint_off)]
        actions += [("type", self.typing(self.solution)), ("key", "enter")]
        for layer in self.stages[self.stage + 1:]:
            actions += [("click", layer.off)] if layer.find else []
            actions += [("type", "".join(_typed(b, w) for b, w in zip(layer.key, layer.widths))), ("key", "enter")]
        return actions

    # ---- finding the pattern
    def _shows(self, idx):
        """True if the key shows through at byte idx: it is in a run of zero
        padding, under this key and no other."""
        lo, hi = self.span
        if not lo <= idx < hi or self.plain[idx]:
            return False
        a = b = idx
        while a > lo and not self.plain[a - 1]:
            a -= 1
        while b < hi and not self.plain[b]:
            b += 1
        return b - a >= len(self.hint)

    def _find(self):
        self.found = True
        self._flash(range(self.hint_off, self.hint_off + len(self.hint)))

    def click(self, idx):
        if self.solved or self.found:
            return None
        if self._shows(idx):
            self._find()
            self.say("found: the key repeats over %s of zero padding" % count(len(self.hint), "byte"), "tan")
            return "ok"
        for k, other in enumerate(self.stages):
            if k != self.stage and other.find and other.off <= idx < other.off + len(other.hint):
                # a double XOR has a pattern for each key, and this is the other one's: no harm done
                self.say("that is zero padding the first key uncovered: look in what is still encrypted"
                         if k < self.stage else "a pattern, but two keys cover it: this is not the first key", "dim")
                return None
        near = self.hint_off - 2 <= idx < self.hint_off + len(self.hint) + 2
        return self._mistake("no key repeats at 0x%04X" % idx, NEAR if near else WRONG)

    # ---- key entry
    def _open(self):
        return [i for i in range(self.keylen) if i not in self.locked]

    def _entries(self):
        """What has been typed, shared out among the key bytes still to type:
        (key byte, its bits or hex digits so far), in order."""
        out, rest = [], self.typed
        for i in self._open():
            out.append((i, rest[:self.widths[i]]))
            rest = rest[self.widths[i]:]
        return out

    def typing(self, key):
        """A key as the characters that type it, the revealed bytes left out."""
        return "".join(_typed(key[i], self.widths[i]) for i in self._open())

    def key_bytes(self):
        """Current key guess: a byte, or None where not fully typed yet."""
        out = [self.locked.get(i) for i in range(self.keylen)]
        for i, got in self._entries():
            if len(got) == self.widths[i]:
                out[i] = int(got, 2 if len(got) == 8 else 16)
        return out

    def key(self, k):
        if self.solved:
            return None
        if k == "backspace":
            self.typed = self.typed[:-1]
        elif not self.found and (k == "enter" or k in HEX_DIGITS):
            self.say("first find where the key repeats", "dim")
        elif len(k) == 1 and k in HEX_DIGITS:
            i = next((i for i, got in self._entries() if len(got) < self.widths[i]), None)
            if i is not None and (k in "01" or self.widths[i] == 2):
                self.typed += k
            elif i is not None:
                self.say("k%d is typed as bits: 0 or 1" % i, "dim")
        elif k == "enter":
            guess = self.key_bytes()
            if None in guess:
                self.say("key is %d byte(s): keep typing" % self.keylen, "dim")
                return None
            if self.validate(guess) and self.stage + 1 < len(self.stages):
                self.say("key %s accepted: it uncovers a second key" % hexs(guess), "amber")
                self._enter(self.stage + 1)
                if self.found:
                    self._flash(range(self.hint_off, self.hint_off + len(self.hint)))
                return "ok"
            if self.validate(guess):
                return self._solve("key %s accepted: payload decrypted" % hexs(guess))
            self.typed = ""
            severity = self.judge(guess)
            note = {NEAR: ": close", WILD: ": nowhere near"}.get(severity, "")
            return self._mistake("key %s rejected%s" % (hexs(guess), note), severity)
        return None

    def judge(self, guess):
        """How bad a wrong key is. NEAR: at least half its bytes are right, or
        it is off by a bit or two (an arithmetic slip). WILD: no byte right
        and half the bits wrong, which is what a blind guess looks like."""
        right = sum(g == k for g, k in zip(guess, self.solution))
        bits = sum(bin(g ^ k).count("1") for g, k in zip(guess, self.solution))
        if bits <= 2 or (self.keylen > 1 and right * 2 >= self.keylen):
            return NEAR
        return WILD if right == 0 and bits >= 4 * self.keylen else WRONG

    # ---- display
    def display(self):
        if self.solved:
            return self.plain
        return xor_bytes(self.cipher, [g or 0 for g in self.key_bytes()], *self.span)

    def styles(self):
        st = {i: "hint" for i in range(self.hint_off, self.hint_off + len(self.hint))} if self.found else {}
        for i in self.flash:
            st[i] = "flash"
        return st

    def summary(self):
        if self.double:
            return "two keys to recover, one after the other, from %d encrypted bytes" % len(self.data)
        return "a %d-byte key to recover from %d encrypted bytes" % (self.keylen, len(self.data))

    def tasks(self):
        guess = self.key_bytes()
        texts = [("Type the bits of k%d = %02X XOR %02X" if self.plain[o] else "Type k%d = %02X XOR %02X")
                 % (i, self.cipher[o], self.plain[o]) for i, o in enumerate(self.known)]
        now = guess.index(None) if None in guess else self.keylen
        if not self.found:      # naming the bytes would give the pattern away
            texts, now = ["Type the key"], -1
        texts.append("Press ENTER to submit the key")
        if self.stages[self.stage].find:
            texts.insert(0, "Find %d bytes where the key repeats" % len(self.hint))
            now += 1
        if self.stage:
            texts.insert(0, "Work out the first key")
            now += 1
        elif self.double:
            texts.append("Then do the same for a second key")
        return self._ordered(texts, now)

    def brief(self):
        keys = ", then ".join(count(len(layer.key), "byte") for layer in self.stages[self.stage:])
        levels = ", then ".join("%d of %d" % (layer.level, len(self.LEVELS)) for layer in self.stages[self.stage:])
        first = ", for the first key" if self.double and not self.stage else ""
        where = "%s, at 0x%04X" % (self.hint_why, self.hint_off)
        if not self.found:
            where = "%s of %s to find" % (count(len(self.hint), "byte"), self.hint_why)
        return [("DO", self.do), ("KEYS" if ", " in keys else "KEY", "%s, repeating" % keys),
                ("KNOWN", where + first),
                ("RULE", "ciphertext XOR plaintext = key"), ("XOR LEVEL", levels)]

    def example(self):
        """One key byte worked out bit by bit: the dump byte over the known one,
        a pointer walking the columns, 0 where they agree and 1 where they differ.
        Over zeros when that is all this node asks: the key comes out as the dump byte.
        And where the zeros have to be found first, that instead: the pointer goes
        to where the key repeats."""
        dump = 0xC7
        worked = any(w == 8 for layer in self.stages for w in layer.widths)
        if not worked and any(layer.find for layer in self.stages):
            return self._example_find()
        known = 0x41 if worked else 0x00       # the letter A, or zero padding
        key = dump ^ known
        dh, kh, out_h = "%02X" % dump, "%02X" % known, "%02X" % key
        d, k, out = _bits8(dump), _bits8(known), _bits8(key)

        def row(label, hx, bits, mark=None, style="fg", hx_style="dim"):
            styled = [(b, "sel" if i == mark else "dim" if b == "_" else style) for i, b in enumerate(bits)]
            pieces = [("%-6s " % label, "dim"), (hx, hx_style), (" = ", "dim")]
            for i, (b, st) in enumerate(styled):
                if i:       # the gap takes its neighbours' style when they agree, so runs merge
                    prev = styled[i - 1][1]
                    pieces.append(("  " if i == 4 else " ", st if st == prev and st != "sel" else "dim"))
                pieces.append((b, st))
            merged = []
            for text, st in pieces:
                if merged and merged[-1][1] == st:
                    merged[-1] = (merged[-1][0] + text, st)
                else:
                    merged.append((text, st))
            return merged

        def under(i, text, style="tan"):       # text starting below bit column i
            return (" " * (12 + 2 * i + (i >= 4)) + text, style)

        frames = [(BEAT, [[("dump   " + dh, "fg")], [("known  " + kh + ("   A" if known else ""), "fg")],
                          [("key    ??", "tan")]]),
                  (BEAT, [row("dump", dh, d), row("known", kh, k), row("key", "__", ["_"] * 8)])]
        for i in range(8):
            got = out[:i + 1] + ["_"] * (7 - i)
            note = "▲ differ 1" if d[i] != k[i] else "▲ same 0"
            frames.append((STEP, [row("dump", dh, d, i), row("known", kh, k, i),
                                  row("key", "__", got, i, "tan"), [under(i, note)]]))
        done = [row("dump", dh, d), row("known", kh, k), row("key", out_h, out, style="tan", hx_style="found")]
        # over zeros the key is read off as hex: each digit under its four bits
        digits = [] if known else [[(" " * 12, "dim"), ("%-9s%s" % tuple(out_h), "found")]]
        frames += [(BEAT, done + digits), (REST, done + [[("KEY > ", "tan"), (out_h, "found")]])]
        return frames

    def _example_find(self):
        n = max(len(layer.key) for layer in self.stages if layer.find)
        key = bytes([0xC7, 0x2B, 0x5E][:n])
        line, start, size = b"\x9a\x3f\x51" + key * (6, 4, 3)[n - 1] + b"\x0e", 3, n * (6, 4, 3)[n - 1]
        run = {start + j: "hint" for j in range(size)}
        frames = [(BEAT, [cells(line), pointer(0), [("the key repeats over zero padding", "dim")]])]
        for here in walk(0, start):
            frames.append((STEP, [cells(line), pointer(here), [("the key repeats over zero padding", "dim")]]))
        found = [cells(line, run), pointer(start, "click")]
        frames += [(BEAT, found + [[("the key repeats over zero padding", "dim")]]),
                   (BEAT, found + [[("%s XOR 00 = " % hexs(key[:1]), "fg"), (hexs(key[:1]), "found")]]),
                   (REST, found + [[("KEY > ", "tan"), (hexs(key), "found")]])]
        return frames

    def _cursor(self):
        """The key byte the next bit or digit goes into; the last one once all
        are typed. None when tools have revealed every byte."""
        entries = self._entries()
        if not entries:
            return None
        return next((i for i, got in entries if len(got) < self.widths[i]), entries[-1][0])

    def panel(self):
        """The key so far, in hex. Under it, only when the key byte the cursor
        is on has to be worked out, the working: the two bytes as bits, and the
        bits typed under them. Over 00 the key shows through: no working."""
        cells, entries = [], dict(self._entries())
        for i in range(self.keylen):
            if i in self.locked:
                cells.append("%02X" % self.locked[i])
            elif self.widths[i] == 2:
                cells.append((entries[i].upper() + "__")[:2])
            else:       # each four bits typed show as their hex digit
                cells.append("".join("%X" % int(entries[i][j:j + 4], 2) if len(entries[i]) >= j + 4 else "_"
                                     for j in (0, 4)))
        lines = [("KEY > " + " ".join(cells), "tan")]
        i = self._cursor()
        if self.solved or i is None or self.widths[i] == 2:
            return lines
        c, pl = self.cipher[self.known[i]], self.plain[self.known[i]]
        got = (entries[i] + "_" * 8)[:8]
        return lines + [("", "fg"), ("  %02X = %s" % (c, _bits(c)), "fg"), ("  %02X = %s" % (pl, _bits(pl)), "fg"),
                        ("  k%d = %s %s" % (i, got[:4], got[4:]), "tan")]

    # ---- tools: both reveal one key byte
    def bruteforce(self):
        open_ = self._open()
        if self.solved or len(open_) <= 0:
            return False
        i = open_[0]
        self.locked[i] = self.solution[i]
        self.typed = ""
        self.say("key byte k%d = %02X revealed" % (i, self.solution[i]), "tan")
        if not self.found:      # and with it, where it repeats
            self._find()
        return True

    def scan(self):
        """SCANNER finds the pattern while there is one to find; after that, a key byte."""
        if self.solved or self.found:
            return self.bruteforce()
        self._find()
        self.say("SCANNER: the key repeats at 0x%04X" % self.hint_off, "tan")
        return True


def _key(rng, n, under=None):
    """A key of n bytes: none of them 00, not all the same, and none the same
    as the byte of the key under it that it sits on, since the two would cancel."""
    while True:
        key = bytes(rng.randrange(1, 256) for _ in range(n))
        if n > 1 and len(set(key)) == 1:
            continue
        if under and any(key[i % n] == under[i % len(under)] for i in range(12)):
            continue
        return key


def _place(rng, lo, hi, cols, size, n):
    """Somewhere from lo up to hi for size known bytes: all in one row of the
    dump, and starting where a key of n bytes starts."""
    starts = [o for o in range(lo, hi - size + 1) if o % n == 0]
    return rng.choice([o for o in starts if o % cols + size <= cols] or starts)


def _typed(b, width):
    """A key byte as the characters that type it: 8 bits, or 2 hex digits."""
    return format(b, "08b" if width == 8 else "02x")


def _bits(b):
    s = format(b, "08b")
    return s[:4] + " " + s[4:]


def _bits8(b):
    return list(format(b, "08b"))
