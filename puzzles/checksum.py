"""CHECKSUM: one header byte is corrupted. Change a byte so the Internet
checksum validates again."""
import random

from packets import PROTO_TCP, fix_checksums, l4_sum, ones_sum

from .base import (BEAT, HEX_DIGITS, MODES_PACKET, NEAR, REST, STEP, WILD, WRONG, Puzzle, PuzzleUnavailable, at,
                   cells, pointer, ramp, walk)


class Checksum(Puzzle):
    kind = "CHECKSUM"
    first = at(2, 4)
    modes = MODES_PACKET
    what = "Checksum repair: one header byte is corrupted. Put it right so the checksum validates."
    do = "Click the corrupted byte and type its right value."
    PAY = 1.4

    TIME = [100, 95, 85, 75, 68, 60]
    OUTLINE_UNTIL = at(3, 4)    # before this the bytes the checksum covers are tinted
    L4_FROM = at(4)             # from here it can be a TCP or UDP checksum, not just IPv4
    ERROR_UNTIL = at(5)         # before this the panel works out how far off the sum is

    @classmethod
    def generate(cls, seed, source, level):
        rng = random.Random(seed)
        p = cls(seed, level)
        want_l4 = level >= cls.L4_FROM and rng.random() < 0.5
        pkt = None
        if want_l4:
            for layer in rng.sample(["TCP", "UDP"], 2):
                cand = source.packet(rng, level, need=("IPv4", layer))
                if cand is not None and cand.info.get("l4_complete") and cand.info.get("l4") == layer:
                    pkt = cand
                    break
        if pkt is None:
            want_l4 = False
            pkt = source.packet(rng, level, need=("IPv4",))
        if pkt is None or pkt.info.get("ip_version") != 4:
            raise PuzzleUnavailable("CHECKSUM needs IPv4 packets")
        info = pkt.info
        # captures often hold blank checksums (offloading): start from a valid frame
        raw = fix_checksums(pkt.raw, pkt)
        p.packet = pkt
        p.ip_start, p.ip_end = info["ip_start"], info["ip_start"] + info["ip_hlen"]
        if want_l4:
            p.target = info["l4"]
            p.l4_start, p.l4_end, p.proto = info["l4_start"], info["l4_end"], info["ip_proto"]
            p.cover = (p.l4_start, p.l4_start + info["l4_hlen"])
            skip = p.l4_start + (16 if p.proto == PROTO_TCP else 6)
            p.field = "tcp.checksum" if p.proto == PROTO_TCP else "udp.checksum"
        else:
            p.target = "IPv4"
            p.cover = (p.ip_start, p.ip_end)
            skip = p.ip_start + 10
            p.field = "ip.checksum"
        p.data = raw
        if p.current_sum() != 0xFFFF:
            raise PuzzleUnavailable("could not normalise the frame's checksum")
        off = rng.choice([i for i in range(*p.cover) if i not in (skip, skip + 1)])
        original = raw[off]
        raw[off] = original ^ rng.randrange(1, 256)
        p.solution = (off, original)
        p.show_error = level < cls.ERROR_UNTIL
        p.time_limit = round(ramp(level, cls.TIME))
        p.cursor = None
        p.typed = ""
        return p

    def _sum_of(self, raw):
        if self.target == "IPv4":
            return ones_sum(raw[self.ip_start:self.ip_end])
        s = self.ip_start
        return l4_sum(raw[s + 12:s + 16], raw[s + 16:s + 20], self.proto, raw[self.l4_start:self.l4_end])

    def current_sum(self):
        return self._sum_of(self.data)

    def validate(self, answer):
        off, value = answer
        if not (0 <= off < len(self.data) and 0 <= value <= 255):
            return False
        trial = bytearray(self.data)
        trial[off] = value
        return self._sum_of(trial) == 0xFFFF

    def solution_actions(self):
        return [("click", self.solution[0]), ("type", "%02x" % self.solution[1])]

    def click(self, idx):
        if self.solved or idx >= len(self.data):
            return None
        self.cursor, self.typed = idx, ""
        return None

    def key(self, k):
        if self.solved:
            return None
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
        if value == self.data[self.cursor]:
            self.say("0x%04X is already %02X" % (self.cursor, value), "dim")
            return None
        if self.validate((self.cursor, value)):
            self.data[self.cursor] = value
            self.learned.append(("field", self.field, "0x%04X" % int.from_bytes(
                self.data[self._csum_pos():self._csum_pos() + 2], "big")))
            return self._solve("%s checksum validates" % self.target)
        severity = self.judge(self.cursor, value)
        note = {NEAR: " (closer)", WILD: ": the checksum does not cover that byte"}.get(severity, "")
        return self._mistake("0x%04X = %02X: checksum still invalid%s" % (self.cursor, value, note), severity)

    def judge(self, off, value):
        """How bad a wrong edit is. NEAR: this byte could have fixed it, and
        the new value is closer to the one that does (right idea, wrong
        amount). WILD: the checksum does not cover this byte at all, so no
        value could have worked."""
        trial = bytearray(self.data)
        trial[off] = value
        if self._sum_of(trial) == self.current_sum():
            return WILD
        fix = next((v for v in range(256) if self.validate((off, v))), None)
        if fix is not None and abs(value - fix) < abs(self.data[off] - fix):
            return NEAR
        return WRONG

    def _csum_pos(self):
        if self.target == "IPv4":
            return self.ip_start + 10
        return self.l4_start + (16 if self.proto == PROTO_TCP else 6)

    def error(self):
        """How far the sum is from valid, signed. The sum wraps round, so the
        same error can be written going up or going down; this picks the form
        one wrong byte produces (a multiple of 0x100, or under 0x100), which
        is the one that says what to fix: +0x0300 is a high-order byte 03 too
        big."""
        up = self.current_sum() % 0xFFFF
        if up == 0:
            return 0
        down = 0xFFFF - up
        one_byte = [v <= 0xFF or v % 0x100 == 0 for v in (up, down)]
        if one_byte[0] != one_byte[1]:
            return up if one_byte[0] else -down
        return up if up <= down else -down

    def error_text(self):
        e = self.error()
        return "none" if e == 0 else "%s0x%04X" % ("+" if e > 0 else "-", abs(e))

    def styles(self):
        st = {}
        if self.level < self.OUTLINE_UNTIL and not self.solved:
            st = {i: "active" for i in range(*self.cover)}
        if self.cursor is not None:
            st[self.cursor] = "sel"
        for i in self.flash:
            st.setdefault(i, "flash")
        return st

    def summary(self):
        return "a corrupted byte to repair under the %s checksum of a %d-byte frame" % (self.target, len(self.data))

    def tasks(self):
        return self._ordered(["Find the corrupted %s header byte" % self.target,
                              "Type its right value"], 0 if self.cursor is None else 1)

    def brief(self):
        lo, hi = (self.ip_start, self.ip_end) if self.target == "IPv4" else (self.l4_start, self.l4_end)
        rows = [("DO", self.do), ("CHECKSUM", "%s, over 0x%04X-0x%04X" % (self.target, lo, hi - 1)),
                ("RULE", "its 16-bit words must sum to FFFF")]
        if self.show_error:
            rows.append(("HELP", "the panel says how far off the sum is"))
        return rows

    def example(self):
        line, bad = bytes.fromhex("4500003B1C46"), 3        # 3B is one too few: the sum comes to FFFE
        fixed = line[:bad] + b"\x3c" + line[bad + 1:]
        wrong, plain, clicked = [("SUM FFFE", "red"), ("   valid = FFFF", "dim")], cells(line), cells(line, {bad: "sel"})

        def edit(typed):
            return [("EDIT > %02X -> %s" % (line[bad], (typed + "__")[:2]), "tan")]

        frames = [(BEAT, [wrong, plain, pointer(0)])]
        frames += [(STEP, [wrong, plain, pointer(i)]) for i in walk(0, bad)]
        frames += [(BEAT, [wrong, clicked, pointer(bad, "click"), edit("")]),
                   (STEP, [wrong, clicked, pointer(bad), edit("3")]),
                   (BEAT, [wrong, clicked, pointer(bad), edit("3C")]),
                   (REST, [[("SUM FFFF   VALID", "fg")], cells(fixed, {bad: "found"})])]
        return frames

    def panel(self):
        s = self.current_sum()
        ok = s == 0xFFFF
        lines = [("TARGET: %s checksum" % self.target, "amber")]
        if self.target == "IPv4":
            lines.append(("  covers header 0x%04X-0x%04X" % (self.ip_start, self.ip_end - 1), "fg"))
            words = ["%02X%02X" % (self.data[i], self.data[i + 1]) for i in range(self.ip_start, self.ip_end, 2)]
            for i in range(0, len(words), 5):
                lines.append(("  " + " ".join(words[i:i + 5]), "dim"))
        else:
            lines.append(("  covers the pseudo-header and the", "fg"))
            lines.append(("  %s 0x%04X-0x%04X" % ("TCP segment" if self.proto == PROTO_TCP else "UDP datagram",
                                                 self.l4_start, self.l4_end - 1), "fg"))
            lines.append(("  corruption is in the %s header" % self.target, "dim"))
        lines += [("", "fg"), ("SUM    0x%04X   (valid = 0xFFFF)" % s, "fg" if ok else "red")]
        if self.show_error or ok:
            lines.append(("ERROR  %s" % self.error_text(), "fg" if ok else "red"))
        lines += [("STATUS %s" % ("VALID" if ok else "INVALID"), "fg" if ok else "red"), ("", "fg")]
        if self.cursor is None:
            lines.append(("EDIT > click a byte", "tan"))
        else:
            lines.append(("EDIT > 0x%04X: %02X -> %s" % (self.cursor, self.data[self.cursor],
                                                        (self.typed.upper() + "__")[:2]), "tan"))
        lines += [("even offset in header = high-order byte", "dim"), ("odd offset = low-order byte", "dim")]
        return lines

    def scan(self):
        if self.solved:
            return False
        self._flash([self.solution[0]], 3.0)
        self.say("SCANNER: corruption at 0x%04X" % self.solution[0], "tan")
        return True
