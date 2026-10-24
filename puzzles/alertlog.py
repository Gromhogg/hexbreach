"""ALERT LOG, an IDS game. The IDS keeps a log of alerts as fixed-size
entries, and some of them are about you. Your address is the pattern: find
every copy of it in a SOURCE field, as in HUNT, and clear that entry's ALERT
byte, then commit the log before it is sent. It is how fixed-size records are
read in a hex dump: a key says where the fields are, the dump gives the rest.
Nothing in the dump marks the ALERT byte: it is found with the key."""
import random

from packets import ip_bytes, ip_str

from .base import (BEAT, HEX_DIGITS, NEAR, REST, STEP, WIDTHS, WILD, WRONG, at, cells, count, hexs, nth, pointer,
                   ramp, step, walk)
from .ids import IdsPuzzle


class AlertLog(IdsPuzzle):
    blurb = "Clear every alert the log holds against your address, then commit it."
    what = "alert log: clear every alert the IDS has logged against your address before the log is sent."
    do = "Find the pattern, then set that entry's ALERT byte to 00."

    TARGETS = [(at(1), 2), (at(3), 3), (at(4), 4), (at(5), 5)]  # entries about you: 2 at the first IDS, 5 at the last
    DECOYS = [(at(1), 0), (at(3), 3), (at(5), 4)]               # IDS 2+: one source a byte off yours, the rest traffic to you
    ENTRIES = [6, 8, 10, 12, 14, 16]                            # entries in the log: an IDS reads 8 to 16
    TIME = [60, 55, 50, 45, 40, 36]                             # about one node's time: 55 s at the first IDS, 36 at the last
    SHUFFLE_FROM = at(4)    # IDS 3: the fields come in a different order each time
    WRAP_FROM = at(4)       # IDS 3: rows no longer line up with entries
    CHECK_FROM = at(5)      # IDS 4: a check byte per entry, broken by clearing the alert
    SIZES = (12, 16)        # bytes an entry may be
    FIELDS = (("time", 4), ("source", 4), ("dest", 4), ("port", 2), ("prio", 1), ("alert", 1))
    PORTS = (80, 443, 53, 22, 25, 445, 3389, 8080)
    WINDOW = 24             # rows of dump on screen: the log is sized to fit

    # ---- generation
    @classmethod
    def generate(cls, seed, source, level, modifiers=()):
        rng = random.Random(seed)
        p = cls(seed, level)
        p.modifiers = list(modifiers)
        n, k, d = round(ramp(level, cls.ENTRIES)), step(level, cls.TARGETS), step(level, cls.DECOYS)
        p.count, p.size = n, rng.choice(cls.SIZES)
        p.has_check = level >= cls.CHECK_FROM
        p.fields = cls._layout(rng, p.size, level >= cls.SHUFFLE_FROM, p.has_check)
        p.offsets, off = {}, 0
        for name, width in p.fields:
            p.offsets[name] = off
            off += width
        if level < cls.WRAP_FROM:
            p.cols = p.size                 # one entry a row
        else:
            fits = [c for c in WIDTHS if c != p.size and n * p.size <= c * cls.WINDOW]
            p.cols = rng.choice(fits or [c for c in WIDTHS if c != p.size])
        p.yours = cls._yours(rng, source, level)
        order = rng.sample(range(n), n)
        p.targets = sorted(order[:k])
        p.decoys = {}
        if d:
            p.decoys[order[k]] = "near"
            for e in order[k + 1:k + d]:
                p.decoys[e] = "dest"
        plain = order[k + d:]
        # about half the other entries are armed too, so the ALERT column gives nothing away
        armed = set(p.targets) | set(p.decoys) | set(rng.sample(plain, (len(plain) + 1) // 2))
        data = bytearray()
        t = rng.randrange(0x5F000000, 0x66000000)
        for e in range(n):
            t += rng.randint(2, 120)
            if e in p.targets:
                src = p.yours
            elif p.decoys.get(e) == "near":
                src = cls._near(rng, p.yours)
            else:
                src = cls._other(rng, p.yours)
            dst = p.yours if p.decoys.get(e) == "dest" else cls._other(rng, p.yours)
            values = {"time": t.to_bytes(4, "big"), "source": src, "dest": dst,
                      "port": rng.choice(cls.PORTS).to_bytes(2, "big"), "prio": bytes([rng.randint(1, 4)]),
                      "alert": bytes([1 if e in armed else 0]), "check": b"\x00"}
            entry = bytearray(b"".join(values[name] for name, _ in p.fields))
            if p.has_check:
                entry[p.offsets["check"]] = cls._xor(entry, p.offsets["check"])
            data += entry
        p.data, p.original = data, bytes(data)
        p.solution = []
        for e in p.targets:
            p.solution.append((p.offset(e, "alert"), 0))
            if p.has_check:     # clearing the alert flips one bit of the check
                p.solution.append((p.offset(e, "check"), p.original[p.offset(e, "check")] ^ 1))
        p.time_limit = round(ramp(level, cls.TIME))
        p.cursor, p.typed = None, ""
        p.found = set()         # the entries whose copy of the pattern has been found
        return p

    @classmethod
    def _layout(cls, rng, size, shuffle, has_check):
        fields = [f for f in cls.FIELDS if size == 16 or f[0] != "time"]
        if has_check:
            fields = [("check", 1) if name == "prio" else (name, width) for name, width in fields]
        if shuffle:
            rng.shuffle(fields)
        assert sum(width for _, width in fields) == size
        return fields

    @staticmethod
    def _yours(rng, source, level):
        """Your address: a real source from the capture when there is one."""
        pkt = source.packet(rng, level, need=("IPv4",))
        if pkt is not None and pkt.info.get("ip_version") == 4:
            addr = ip_bytes(pkt.info["src_ip"])
            if addr not in (bytes(4), b"\xff" * 4):
                return addr
        return bytes([10, rng.randrange(256), rng.randrange(256), rng.randrange(1, 255)])

    @staticmethod
    def _other(rng, yours):
        """An address that starts like yours, so it has to be read, and differs in at least two bytes."""
        while True:
            addr = bytes([yours[0]] + [rng.randrange(256) for _ in range(3)])
            if sum(a != b for a, b in zip(addr, yours)) >= 2:
                return addr

    @staticmethod
    def _near(rng, yours):
        """Yours with one byte changed."""
        addr, j = bytearray(yours), rng.randrange(4)
        addr[j] = (addr[j] + rng.randrange(1, 256)) % 256
        return bytes(addr)

    @staticmethod
    def _xor(entry, skip):
        value = 0
        for i, b in enumerate(entry):
            if i != skip:
                value ^= b
        return value

    # ---- the log
    def offset(self, e, name):
        return e * self.size + self.offsets[name]

    def role(self, idx):
        """(entry, field) of a byte."""
        e, rel = divmod(idx, self.size)
        name = next(n for n, w in self.fields if self.offsets[n] <= rel < self.offsets[n] + w)
        return e, name

    def entry(self, e, buf=None):
        buf = self.data if buf is None else buf
        return buf[e * self.size:(e + 1) * self.size]

    def source_of(self, e):
        return ip_str(self.entry(e)[self.offsets["source"]:self.offsets["source"] + 4])

    def left(self, buf=None):
        """The entries about you that are still armed."""
        buf = self.data if buf is None else buf
        return [e for e in self.targets if buf[self.offset(e, "alert")] != 0]

    def broken(self, buf=None):
        """The entries whose CHECK byte no longer matches."""
        if not self.has_check:
            return []
        skip = self.offsets["check"]
        return [e for e in range(self.count) if self.entry(e, buf)[skip] != self._xor(self.entry(e, buf), skip)]

    def _fix_check(self, e):
        self.data[self.offset(e, "check")] = self._xor(self.entry(e), self.offsets["check"])

    # ---- checking
    def validate(self, answer):
        """answer is (byte index, new value) edits, on your entries' ALERT and
        CHECK bytes only: valid when they leave no alert armed and no check broken."""
        trial = bytearray(self.original)
        for idx, value in answer:
            if not (0 <= idx < len(trial) and 0 <= value <= 255):
                return False
            e, name = self.role(idx)
            if e not in self.targets or name not in ("alert", "check"):
                return False
            trial[idx] = value
        return not self.left(trial) and not self.broken(trial)

    def solution_actions(self):
        actions = []
        for idx, value in self.solution:
            actions += [("click", idx), ("type", "%02x" % value)]
        return actions + [("key", "enter")]

    # ---- input
    def click(self, idx):
        if self.solved or idx >= len(self.data):
            return None
        e, name = self.role(idx)
        if name in ("source", "dest"):
            return self._find(idx, e, name)
        self.cursor, self.typed = idx, ""
        return None

    def _find(self, idx, e, name):
        """A click on an address, as in HUNT: the pattern in SOURCE is a match,
        any other address is a mistake."""
        if name == "source" and e in self.targets:
            if e in self.found:
                return None
            self.found.add(e)
            self.say("match at 0x%04X  (%d/%d)" % (self.offset(e, "source"), len(self.found), len(self.targets)))
            return "ok"
        if name == "dest" and self.decoys.get(e) == "dest":
            return self._mistake("0x%04X: that copy is in DEST, not SOURCE" % idx, NEAR)
        if name == "source" and self.decoys.get(e) == "near":
            start = self.offset(e, "source")
            j = next(j for j in range(4) if self.data[start + j] != self.yours[j])
            return self._mistake("lookalike: byte %d is %02X, not %02X" % (j + 1, self.data[start + j], self.yours[j]),
                                 NEAR)
        return self._mistake("0x%04X is not part of the pattern" % idx)

    def key(self, k):
        if self.solved:
            return None
        if k == "enter":
            return self._commit()
        if k == "backspace":
            self.typed = self.typed[:-1]
            return None
        if len(k) != 1 or k not in HEX_DIGITS:
            return None
        if self.cursor is None:
            self.say("click the byte you want to change first", "dim")
            return None
        self.typed += k
        if len(self.typed) < 2:
            return None
        value, self.typed = int(self.typed, 16), ""
        return self._edit(self.cursor, value)

    def _edit(self, idx, value):
        """A mistake never writes the byte. A wrong byte drops the cursor; a
        wrong value on the right byte keeps it."""
        if value == self.data[idx]:
            self.say("0x%04X is already %02X" % (idx, value), "dim")
            return None
        e, name = self.role(idx)
        if name == "alert":
            if e in self.targets:
                if value != 0:
                    return self._mistake("0x%04X = %02X: the log reads 00 as cleared, nothing else" % (idx, value),
                                         WRONG)
                self.data[idx] = 0
                self.found.add(e)       # cleared without a click on its pattern: found all the same
                self.say("alert cleared at 0x%04X  (%d/%d)" % (
                    idx, len(self.targets) - len(self.left()), len(self.targets)), "fg")
                return "ok"
            self.cursor = None
            kind, src = self.decoys.get(e), self.source_of(e)
            if kind == "dest":
                return self._mistake("0x%04X: that entry has the pattern in DEST; its SOURCE is %s" % (idx, src), NEAR)
            if kind == "near":
                return self._mistake("0x%04X: SOURCE %s is one byte off the pattern" % (idx, src), NEAR)
            return self._mistake("0x%04X: SOURCE %s is not the pattern" % (idx, src), WRONG)
        if name == "check":
            if e in self.targets and e in self.broken():
                if value == self._xor(self.entry(e), self.offsets["check"]):
                    self.data[idx] = value
                    self.say("check fixed at 0x%04X" % idx, "fg")
                    return "ok"
                return self._mistake("0x%04X = %02X: not the XOR of the other %d bytes" % (idx, value, self.size - 1),
                                     NEAR)
            self.cursor = None
            return self._mistake("0x%04X: that CHECK byte is right as it is" % idx, WRONG)
        self.cursor = None
        what = "an ALERT byte" + (" or a CHECK byte" if self.has_check else "")
        return self._mistake("0x%04X is not %s (that is %s)" % (idx, what, name.upper()), WILD)

    def _commit(self):
        """ENTER: the log is sent. Anything still armed or failing its check
        gets it rejected; one thing left is a near miss."""
        left, bad = self.left(), self.broken()
        if not left and not bad:
            return self._solve("log committed: nothing in it points at you")
        e, name = (left[0], "alert") if left else (bad[0], "check")
        idx = self.offset(e, name)
        self._flash([idx], 2.0)
        if len(left) + len(bad) == 1:
            what = "is still armed" if left else "fails its check"
            return self._mistake("log rejected: entry %d at 0x%04X %s" % (e + 1, idx, what), NEAR)
        parts = []
        if left:
            parts.append("%s still armed" % count(len(left), "alert"))
        if bad:
            parts.append("%s fail%s" % (count(len(bad), "check"), "s" if len(bad) == 1 else ""))
        return self._mistake("log rejected: " + ", ".join(parts), WRONG)

    # ---- display
    def styles(self):
        """The copies found and the bytes put right. Which byte is an ALERT
        or a CHECK byte is never marked: the key says where they are."""
        st = {}
        for e in self.found:
            start = self.offset(e, "source")
            st.update(dict.fromkeys(range(start, start + 4), "found"))
        for e in self.targets:
            for name in ("alert", "check")[:1 + self.has_check]:
                idx = self.offset(e, name)
                if self.data[idx] != self.original[idx]:
                    st[idx] = "found"
        if self.cursor is not None:
            st[self.cursor] = "sel"
        for i in self.flash:
            st.setdefault(i, "flash")
        return st

    def layers(self):
        """One band per entry: with a DISSECTOR held, the dump marks where each starts."""
        return [("entry %d" % (e + 1), e * self.size, (e + 1) * self.size) for e in range(self.count)]

    def tasks(self):
        left, bad = self.left(), self.broken()
        # as in HUNT: the bytes to find, and how many copies. With decoys about, which field counts
        texts = ["Find %s%s (%d/%d)" % (hexs(self.yours), " in SOURCE" if self.decoys else "",
                                        len(self.found), len(self.targets)),
                 "Set its ALERT byte to 00 (%d/%d)" % (len(self.targets) - len(left), len(self.targets))]
        if self.has_check:
            texts.append("Fix its CHECK byte: XOR of the rest")
        texts.append("Press ENTER to commit the log")
        if not left and not bad:
            now = len(texts) - 1
        elif bad:
            now = 2
        elif any(e in self.found for e in left):
            now = 1     # a copy has been found: its entry's alert is next
        else:
            now = 0
        return self._ordered(texts, now)

    def summary(self):
        return "an IDS alert log of %d entries, %d of them about you" % (self.count, len(self.targets))

    def brief(self):
        rows = [("DO", self.do), ("PATTERN", "%s, your address" % hexs(self.yours)),
                ("COPIES", "%d, in %d entries of %d bytes" % (len(self.targets), self.count, self.size))]
        if self.decoys:
            rows.append(("FAKES", "a copy in DEST, and a SOURCE one byte off"))
        if self.has_check:
            rows.append(("CHECK", "XOR of the entry's other bytes: fix it too"))
        return rows

    def example(self):
        """A short entry (source, port, prio, alert), never this node's: the
        pattern is clicked, the key says where its ALERT byte is, the pointer
        goes there and 00 goes in. The key reads the way this node's does."""
        line, alert = bytes.fromhex("0A04020901BB0201"), 7
        lined = self.cols == self.size
        where = "column %02X" % alert if lined else "%s byte after the pattern" % nth(alert - 3)
        head = [[("PATTERN  0A 04 02 09", "fg")], [("ALERT    " + where, "fg")]]
        if lined:   # the column numbers along the top of the dump
            head.append([(" ".join("%02X" % i for i in range(len(line))), "dim")])
        src = {i: "found" for i in range(4)}
        clicked = cells(line, {**src, alert: "sel"})
        frames = [(BEAT, head + [cells(line), pointer(3)]),
                  (BEAT, head + [cells(line, src), pointer(3, "click")])]
        # with no columns to go by, the pointer counts its way there
        frames += [(STEP, head + [cells(line, src), pointer(i, "" if lined else nth(i - 3))]) for i in walk(3, alert)]
        frames += [(BEAT, head + [clicked, pointer(alert, "click")]),
                   (BEAT, head + [clicked, pointer(alert, "type 00")]),
                   (REST, head + [cells(line[:alert] + b"\x00", {**src, alert: "found"}), pointer(alert, "[ENTER]")])]
        return frames

    def key_rows(self):
        """The key: where SOURCE, ALERT and CHECK are. While a row of the dump
        is one entry, they are columns. Once rows no longer line up with
        entries, ALERT and CHECK are counted from the pattern instead."""
        source = self.offsets["source"]
        marks = [name for name in ("alert", "check") if name in self.offsets]
        if self.cols == self.size:
            rows = [("SOURCE", "columns %02X-%02X" % (source, source + 3))]
            rows += [(name.upper(), "column %02X" % self.offsets[name]) for name in marks]
        else:
            rows = [("ENTRY", "%d bytes long" % self.size),
                    ("SOURCE", "starts %s into an entry" % count(source, "byte") if source
                     else "the first 4 bytes of an entry")]
            for name in marks:
                off = self.offsets[name]
                rows.append((name.upper(), "%s byte after the pattern" % nth(off - source - 3) if off > source
                             else "%s byte before the pattern" % nth(source - off)))
        return rows

    def panel(self):
        """Only what the log cannot be read without: the key to where the
        fields the steps name are. Then the byte being edited."""
        lines = [("KEY", "amber")] + [("  %-7s %s" % row, "fg") for row in self.key_rows()]
        if self.cursor is not None:
            lines += [("", "fg"), ("EDIT > 0x%04X: %02X -> %s" % (self.cursor, self.data[self.cursor],
                                                                  (self.typed.upper() + "__")[:2]), "tan")]
        return lines

    # ---- tool hooks
    def scan(self):
        """SCANNER: flash an entry about you that is still armed, or a check that fails."""
        left, bad = self.left(), self.broken()
        if self.solved or not (left or bad):
            return False
        if left:
            idx = self.offset(left[0], "alert")
            self.say("SCANNER: entry %d at 0x%04X is about you" % (left[0] + 1, idx), "tan")
        else:
            idx = self.offset(bad[0], "check")
            self.say("SCANNER: entry %d fails its check at 0x%04X" % (bad[0] + 1, idx), "tan")
        self._flash([idx], 3.0)
        return True

    def bruteforce(self):
        """BRUTEFORCE: clear one alert about you, check and all, or fix a check that fails."""
        left, bad = self.left(), self.broken()
        if self.solved or not (left or bad):
            return False
        if left:
            e = left[0]
            self.data[self.offset(e, "alert")] = 0
            self.found.add(e)
            text = "BRUTEFORCE: alert at 0x%04X cleared" % self.offset(e, "alert")
            if self.has_check:
                self._fix_check(e)
                text += ", its check fixed"
        else:
            e = bad[0]
            self._fix_check(e)
            text = "BRUTEFORCE: check at 0x%04X fixed" % self.offset(e, "check")
        self.say(text, "tan")
        return True
