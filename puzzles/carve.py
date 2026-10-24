"""CARVE: files are embedded in the stream. Find each one by its signature (its
magic number) and say what it is. In forensics this is file carving."""
import random

from .base import (BEAT, NEAR, REST, STEP, WILD, Puzzle, PuzzleUnavailable, at, cells, count, hexs, pick_cols,
                   pointer, printable, ramp, spread, step)
from .hunt import find_all

# name -> (signature, plausible bytes that follow, description, first subnet)
# All real. None of them spells its own type in the ASCII pane, tail included:
# a file that prints "PDF" or "GIF89a" beside its bytes is no test at all.
SIGNATURES = {
    "ZIP": (b"PK\x03\x04", b"\x14\x00\x00\x00\x08\x00", "ZIP archive (also docx, jar, apk)", 1),
    "JPEG": (b"\xff\xd8\xff\xdb", b"\x00\x43\x00\x08\x06\x06\x07\x06", "JPEG image", 1),
    "GZIP": (b"\x1f\x8b\x08", b"\x00\x5e\x2a\x91\x65\x00\x03", "gzip stream", 1),
    "EXE": (b"MZ\x90\x00", b"\x03\x00\x00\x00\x04\x00\x00\x00", "Windows executable (PE)", 1),
    "BZIP2": (b"BZh", b"91AY&SY\x8a\x1c", "bzip2 stream", 1),
    "TIFF": (b"II*\x00", b"\x08\x00\x00\x00\x0e\x00\x00\x01", "TIFF image", 1),
    "CLASS": (b"\xca\xfe\xba\xbe", b"\x00\x00\x00\x41\x00\x1d", "Java class file", 1),
    "MACHO": (b"\xcf\xfa\xed\xfe", b"\x0c\x00\x00\x01\x00\x00\x00\x00", "Mach-O executable (macOS)", 1),
    "PCAP": (b"\xd4\xc3\xb2\xa1", b"\x02\x00\x04\x00\x00\x00", "pcap capture file", 1),
    "PCAPNG": (b"\x0a\x0d\x0d\x0a", b"\x1c\x00\x00\x00\x4d\x3c\x2b\x1a", "pcapng capture file", 2),
    "OLE2": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", b"\x00\x00\x00\x00\x00\x00",
             "OLE2 compound file (old .doc, .xls)", 3),
    "ZSTD": (b"\x28\xb5\x2f\xfd", b"\x24\x80\x45\x02\x00\x93", "Zstandard stream", 4),
    "MIDI": (b"MThd", b"\x00\x00\x00\x06\x00\x01\x00\x02", "MIDI music file", 5),
}
# Formats whose signature does print their name. They are never asked about;
# the field manual lists them as they read in the ASCII pane.
SELF_NAMING = ["\x89PNG", "%PDF-", "GIF89a", "\x7fELF", "Rar!", "7z", "SQLite", "OggS"]


def signatures_in(data):
    """Every (offset, name) where a known signature occurs."""
    hits = []
    for name, (magic, _, _, _) in SIGNATURES.items():
        hits += [(pos, name) for pos in find_all(data, magic)]
    return sorted(hits)


class Carve(Puzzle):
    kind = "CARVE"
    do = "Click each file's signature, then name the file."
    what = "File carving: recover files from raw bytes by their signatures (their magic numbers)."
    PAY = 0.9

    SIZE = [64, 144, 224, 304, 384, 448]
    KNOWN = [(at(1), 4), (at(3), 5), (at(5), 6)]     # signatures in play on a node, out of those unlocked
    FILES = [(at(1), 1), (at(3), 2), (at(5), 3)]
    DECOYS = [(at(1), 0), (at(1, 4), 1), (at(2, 4), 2), (at(4), 3), (at(5, 4), 4)]
    TIME = [90, 75, 64, 56, 52, 50]

    @classmethod
    def generate(cls, seed, source, level):
        rng = random.Random(seed)
        cols = pick_cols(rng)
        size = max(spread(rng, ramp(level, cls.SIZE), cols), 48 // cols * cols + cols)
        unlocked = [n for n, sig in SIGNATURES.items() if sig[3] <= level]
        pool = rng.sample(unlocked, min(step(level, cls.KNOWN), len(unlocked)))
        pool.sort(key=list(SIGNATURES).index)
        base = bytearray(source.buffer(size, rng, level=level))
        while len(base) < size:
            base.append(rng.getrandbits(8))
        for _ in range(60):
            p = cls._attempt(seed, level, rng, base, pool)
            if p is not None:
                p.cols = cols
                return p
        raise PuzzleUnavailable("could not hide files cleanly")

    @classmethod
    def _attempt(cls, seed, level, rng, base, pool):
        data = bytearray(base)
        # the stream itself must not contain a real signature
        for _ in range(64):
            hits = signatures_in(data)
            if not hits:
                break
            for pos, name in hits:
                data[pos + len(SIGNATURES[name][0]) - 1] ^= 0x55
        else:
            return None
        names = rng.sample(pool, step(level, cls.FILES))
        decoys = [rng.choice(pool) for _ in range(step(level, cls.DECOYS))]
        spots = cls._spots(rng, len(data), len(names) + len(decoys))
        if spots is None:
            return None
        files = []
        for name, pos in zip(names, spots):
            magic, tail = SIGNATURES[name][:2]
            data[pos:pos + len(magic) + len(tail)] = magic + tail
            files.append((pos, name))
        decoy_ranges = []
        for name, pos in zip(decoys, spots[len(names):]):
            magic = SIGNATURES[name][0]
            keep = max(2, len(magic) // 2)
            broken = magic[:keep] + bytes(b ^ rng.randrange(1, 256) for b in magic[keep:])
            data[pos:pos + len(broken)] = broken
            decoy_ranges.append((pos, pos + len(broken)))
        files.sort()
        if signatures_in(data) != files:
            return None
        p = cls(seed, level)
        p.data = data
        p.files = files
        p.decoys = decoy_ranges
        p.pool = pool
        p.options = []
        for _ in files:
            opts = list(pool)
            rng.shuffle(opts)
            p.options.append(opts)
        p.solution = list(files)
        p.luck = rng.uniform(0.85, 1.15)     # a little either way, which the pay makes up for
        p.time_limit = round(ramp(level, cls.TIME) * p.luck)
        p.found = set()         # indices into files
        p.pending = None        # file index awaiting identification
        return p

    @staticmethod
    def _spots(rng, size, count):
        """count offsets, each with 24 clear bytes after it."""
        spots = []
        for _ in range(400):
            if len(spots) == count:
                return spots
            pos = rng.randrange(0, size - 24)
            if all(abs(pos - q) >= 24 for q in spots):
                spots.append(pos)
        return None

    def difficulty(self):
        # next to what this level usually brings: the level itself already raises the pay
        files = len(self.files)
        d = 1.0 + 0.2 * (len(self.data) / ramp(self.level, self.SIZE) - 1)
        d += 0.15 * (files - step(self.level, self.FILES)) + 0.08 * (len(self.decoys) - step(self.level, self.DECOYS))
        # a signature that reads as letters ("PK", "MZ", "BZh") stands out in the ASCII pane
        loud = sum(sum(chr(b).isalpha() for b in SIGNATURES[name][0] if b < 127) >= 2 for _, name in self.files)
        d -= 0.3 * (loud / files - 0.4)
        d -= 0.6 * (self.luck - 1)          # a short timer pays more
        return max(0.6, min(1.4, d))

    def validate(self, answer):
        return sorted((int(pos), name) for pos, name in answer) == self.files == signatures_in(self.data)

    def solution_actions(self):
        actions = []
        for i, (pos, name) in enumerate(self.files):
            actions.append(("click", pos))
            actions.append(("key", str(self.options[i].index(name) + 1)))
        return actions

    def _extent(self, i):
        pos, name = self.files[i]
        return pos, pos + len(SIGNATURES[name][0])

    def click(self, idx):
        if self.solved:
            return None
        if self.pending is not None:
            self.say("identify the file first: press 1-%d" % len(self.pool), "dim")
            return None
        for i in range(len(self.files)):
            lo, hi = self._extent(i)
            if lo <= idx < hi:
                if i in self.found:
                    return None
                self.pending = i
                self.say("signature at 0x%04X: what is it?" % lo, "amber")
                return "ok"
        if any(lo <= idx < hi for lo, hi in self.decoys):
            return self._mistake("decoy: that signature is incomplete")
        # past the signature but still inside the file: they found it, and clicked its body
        for pos, name in self.files:
            magic, tail = SIGNATURES[name][:2]
            if pos + len(magic) <= idx < pos + len(magic) + len(tail):
                return self._mistake("that is inside a file: click its signature, at the start", NEAR)
        # a byte that at least opens one of the known signatures is a fair guess; anything else is not
        if any(SIGNATURES[name][0][0] == self.data[idx] for name in self.pool):
            return self._mistake("nothing starts at 0x%04X" % idx)
        return self._mistake("nothing starts at 0x%04X: no signature begins with %02X" % (idx, self.data[idx]), WILD)

    def key(self, k):
        if self.solved or self.pending is None or len(k) != 1 or k not in "123456789"[:len(self.pool)]:
            return None
        i = self.pending
        pos, name = self.files[i]
        choice = self.options[i][int(k) - 1]
        if choice != name:
            return self._mistake("not a %s file" % choice)
        self.pending = None
        self.found.add(i)
        self.learned.append(("signature", name, hexs(SIGNATURES[name][0])))
        if len(self.found) == len(self.files):
            return self._solve("%s recovered: stream is clean" % SIGNATURES[name][2])
        self.say("%s recovered at 0x%04X (%d/%d)" % (SIGNATURES[name][2], pos, len(self.found),
                                                    len(self.files)))
        return "ok"

    def tasks(self):
        # no count here: the panel's FILES RECOVERED line is the one place that says it
        return self._ordered(["Find a file signature", "Name it: press 1-%d" % len(self.pool)],
                             1 if self.pending is not None else 0)

    def summary(self):
        decoys = ", with %s" % count(len(self.decoys), "decoy") if self.decoys else ""
        return "%s hidden in %d bytes%s" % (count(len(self.files), "file"), len(self.data), decoys)

    def brief(self):
        rows = [("DO", self.do), ("FILES", "%d, in %d bytes" % (len(self.files), len(self.data)))]
        if self.decoys:
            rows.append(("DECOYS", "%d: signatures that are cut short" % len(self.decoys)))
        return rows

    def example(self):
        hidden = {name for _, name in self.files}
        name = next((n for n in self.pool if n not in hidden), self.pool[0])    # never a file that is on this node
        magic = SIGNATURES[name][0]
        line = b"\xa7" + magic + b"\x14\x00"
        plain = cells(line)
        clicked = cells(line, dict.fromkeys(range(1, 1 + len(magic)), "sel"))
        named = cells(line, dict.fromkeys(range(1, len(line)), "found"))
        others = [n for n in self.pool if n != name]
        options = [others[0], name, others[1]]

        def answers(given):
            row = []
            for i, option in enumerate(options):
                row += [("[%d] %s" % (i + 1, option), "sel" if given and option == name else "tan"), ("  ", "tan")]
            return row

        return [(BEAT, [plain, pointer(0)]),
                (STEP, [plain, pointer(1)]),
                (BEAT, [clicked, pointer(1, "click"), answers(False)]),
                (BEAT, [clicked, pointer(1), answers(True)]),
                (REST, [named, [], answers(True)])]

    def styles(self):
        # nothing in the dump is marked: the signatures have to be read out of the bytes
        st = {}
        for i in self.found:
            pos, name = self.files[i]
            for j in range(pos, pos + len(SIGNATURES[name][0]) + len(SIGNATURES[name][1])):
                st[j] = "found"
        if self.pending is not None:
            lo, hi = self._extent(self.pending)
            for j in range(lo, hi):
                st[j] = "sel"
        for i in self.flash:
            st.setdefault(i, "flash")
        return st

    def panel(self):
        count = "%d/%d" % (len(self.found), len(self.files))
        if self.pending is not None:
            lines = [("WHAT IS IT?   (%s recovered)" % count, "amber")]
            # the answers are the names in the table below, word for word: no longer description to decode
            for n, name in enumerate(self.options[self.pending]):
                lines.append(("  [%d] %s" % (n + 1, name), "tan", str(n + 1)))
        else:
            lines = [("FILES RECOVERED %s" % count, "amber")]
        lines += [("", "fg"), ("KNOWN SIGNATURES", "amber")]
        for name in self.pool:
            magic = SIGNATURES[name][0]
            # beside the bytes, how they read in the ASCII pane, when any of them is a letter: ZIP is "PK.."
            lettered = len(magic) <= 4 and any(chr(b).isalnum() for b in magic if b < 127)
            reads = printable(magic, self.codepage) if lettered else ""
            lines.append((("  %-6s %-11s  %s" % (name, hexs(magic), reads)).rstrip(), "fg"))
        return lines

    def scan(self):
        left = [i for i in range(len(self.files)) if i not in self.found]
        if self.solved or not left:
            return False
        row = self.files[left[0]][0] // self.cols * self.cols
        self._flash(range(row, min(row + self.cols, len(self.data))), 3.0)
        self.say("SCANNER: something starts in row 0x%04X" % row, "tan")
        return True
