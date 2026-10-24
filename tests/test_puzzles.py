"""Every generated puzzle must be solvable: for 1,000 seeds per puzzle type and
data mode, spread over every hop of a run, the generator's own solution passes
its validator, and replaying that solution through the puzzle's input methods
solves it with no mistakes."""
import os
import random
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import puzzles  # noqa: E402
import run as runmod  # noqa: E402
import sources  # noqa: E402
from puzzles import HOPS, REGISTRY, apply_actions, at, kinds_for_mode, ramp, step  # noqa: E402
from puzzles.alertlog import AlertLog  # noqa: E402
from puzzles.hunt import find_all  # noqa: E402
from puzzles.carve import signatures_in  # noqa: E402

SEEDS = 1000
LAST = at(runmod.SUBNETS, HOPS + 1)     # level of the final IDS
_sources = {}


def level_for(seed):
    """A level for a seed, cycling through every hop of every subnet."""
    return at(1 + seed % runmod.SUBNETS, 1 + seed // runmod.SUBNETS % (HOPS + 1))


def run_levels():
    """(subnet, hop, level) for every node position in a run, in order."""
    return [(s, h, at(s, h)) for s in range(1, runmod.SUBNETS + 1) for h in range(1, HOPS + 2)]


def bits(b):
    """A byte as the side panel writes it: 1000 0010."""
    return format(b >> 4, "04b") + " " + format(b & 15, "04b")


def source(mode):
    if mode not in _sources:
        if mode == "RAW":
            _sources[mode] = sources.RandomSource()
        elif mode == "PROTOCOL":
            _sources[mode] = sources.SynthSource()
        else:
            # LIVE reads a capture from disk, like the real thing
            directory = tempfile.mkdtemp(prefix="hexbreach-test-")
            rng, syn, frames = random.Random(77), sources.SynthSource(), []
            for i in range(60):
                frames += syn.flow(rng, 1 + i % 5)
            frames += [syn.make(kind, rng) for _, kind, _ in sources.SYNTH_KINDS for _ in range(6)]
            sources.write_pcap(os.path.join(directory, "a.pcap"), frames[::2])
            sources.write_pcapng(os.path.join(directory, "b.pcapng"), frames[1::2])
            src = sources.PcapSource(directory)
            assert not src.using_fallback
            _sources[mode] = src
    return _sources[mode]


def ids_key_ok(test, p, where):
    """The side panel is the key and nothing else, and following it from a
    copy of the pattern lands on that entry's ALERT and CHECK bytes."""
    rows = [row[0] for row in p.panel()]
    test.assertEqual(rows[0], "KEY", where)
    key = {row[2:9].strip(): row[10:] for row in rows[1:]}
    test.assertEqual(len(key), len(rows) - 1, where)
    marks = ["ALERT"] + (["CHECK"] if p.has_check else [])
    lined = p.cols == p.size
    test.assertEqual(list(key), ([] if lined else ["ENTRY"]) + ["SOURCE"] + marks, where)
    for e in p.targets:
        start = p.offset(e, "source")
        if lined:       # a row is an entry: the key names columns of the dump
            test.assertEqual(key["SOURCE"], "columns %02X-%02X" % (start % p.cols, (start + 3) % p.cols), where)
        else:           # rows wrap: the key says how big an entry is and where SOURCE is in it
            test.assertEqual(key["ENTRY"], "%d bytes long" % p.size, where)
            into = start % p.size
            test.assertIn(key["SOURCE"], ("starts %d byte%s into an entry" % (into, "" if into == 1 else "s"),
                                          "the first 4 bytes of an entry"), where)
            test.assertEqual(key["SOURCE"].startswith("the first"), into == 0, where)
        for name in marks:
            idx, text = p.offset(e, name.lower()), key[name]
            if lined:
                test.assertEqual(text, "column %02X" % (idx % p.cols), where)
                continue
            n, way = re.fullmatch(r"(\d+)(?:st|nd|rd|th) byte (after|before) the pattern", text).groups()
            test.assertEqual(start + 3 + int(n) if way == "after" else start - int(n), idx, (where, text))


class SolvableTest(unittest.TestCase):
    def check(self, mode, kind):
        src = source(mode)
        for seed in range(SEEDS):
            level = level_for(seed)
            p = REGISTRY[kind].generate(seed, src, level)
            where = "%s %s seed=%d level=%.2f" % (mode, kind, seed, level)
            self.assertTrue(p.validate(p.solution), where)
            self.assertGreater(p.time_limit, 0, where)
            self.assertGreater(len(p.data), 0, where)
            self.assertEqual([s for _, s in p.tasks()], ["now"] + ["todo"] * (len(p.tasks()) - 1), where)
            results = self.walk(p, where)
            self.assertTrue(p.solved, where)
            self.assertEqual(p.mistakes, 0, where)
            self.assertEqual(results[-1], "solved", where)

    def walk(self, p, where):
        """Replay the known solution one input at a time, as a player would,
        checking the task list after every one."""
        self.tasks_ok(p, where)
        results = []
        for action in p.solution_actions():
            # a keystroke at a time
            for one in ([("type", ch) for ch in action[1]] if action[0] == "type" else [action]):
                results += apply_actions(p, [one])
                self.tasks_ok(p, where)
        return results

    def tasks_ok(self, p, where):
        """1 to 5 short steps; one is current until the puzzle is solved and
        all are done after; the line above the dump is the current step."""
        tasks = p.tasks()
        states = [state for _, state in tasks]
        self.assertTrue(1 <= len(tasks) <= 5, (where, tasks))
        self.assertTrue(all(text and len(text) <= 64 for text, _ in tasks), (where, tasks))
        self.assertTrue(set(states) <= {"done", "now", "todo"}, (where, tasks))
        if p.solved:
            self.assertEqual(set(states), {"done"}, (where, tasks))
        else:
            self.assertEqual(states.count("now"), 1, (where, tasks))
            self.assertEqual(p.prompt(), tasks[states.index("now")][0], where)
        p.panel(), p.styles(), p.display()      # must not raise in any state

    def test_modes_offer_the_right_puzzles(self):
        self.assertEqual(sorted(kinds_for_mode("RAW")), ["CARVE", "HUNT", "PAYLOAD", "REASSEMBLE", "XOR"])
        for mode in ("PROTOCOL", "LIVE"):
            self.assertEqual(sorted(kinds_for_mode(mode)), ["CARVE", "CHECKSUM", "DISSECT", "HUNT", "PAYLOAD",
                                                         "REASSEMBLE", "XOR"])

    def ids(self, mode, subnet, seed):
        """The IDS at the end of a subnet."""
        return puzzles.ids.generate(seed, source(mode), at(subnet, HOPS + 1))

    def test_ids(self):
        """The IDS holds ALERT LOG: a log with a few entries about you, and a
        known set of edits that clears them, played through the inputs."""
        for mode in ("RAW", "PROTOCOL", "LIVE"):
            for subnet in range(1, runmod.SUBNETS + 1):
                level = at(subnet, HOPS + 1)
                for seed in range(60):
                    p = self.ids(mode, subnet, seed)
                    where = "%s subnet=%d seed=%d" % (mode, subnet, seed)
                    self.assertIsInstance(p, AlertLog, where)
                    self.assertEqual(p.kind, "IDS", where)
                    self.assertTrue(p.what.startswith("alert log:"), where)
                    self.assertEqual(len(p.data), p.count * p.size, where)
                    self.assertEqual(len(p.targets), step(level, AlertLog.TARGETS), where)
                    self.assertGreater(p.time_limit, 0, where)
                    self.assertTrue(p.validate(p.solution), where)
                    self.assertEqual([s for _, s in p.tasks()], ["now"] + ["todo"] * (len(p.tasks()) - 1), where)
                    results = self.walk(p, where)
                    self.assertEqual((p.solved, p.mistakes, results[-1]), (True, 0, "solved"), where)
                    p.brief(), p.example(), p.summary()
                    self.assertTrue(all(len(e[0]) <= 41 for e in p.panel()), where)     # the side panel's width
                    self.assertLessEqual(len(p.brief()), 5, where)
                    self.assertTrue(all(len(piece[0]) <= 38 for _, rows in p.example() for row in rows
                                        for piece in [("".join(t for t, _ in row), 0)]), where)

    def test_ids_key_reads_as_columns_then_as_counts(self):
        """The first two IDS name columns; from the third, rows wrap and the key counts from the pattern."""
        from puzzles.base import nth
        self.assertEqual([nth(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22)],
                         ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd"])
        for subnet in range(1, runmod.SUBNETS + 1):
            for seed in range(40):
                p = self.ids("PROTOCOL", subnet, seed)
                ids_key_ok(self, p, (subnet, seed))
                self.assertEqual(any("column" in row[0] for row in p.panel()), subnet <= 2, (subnet, seed))
                # the briefing's example reads the same way as this node's key
                shown = {"".join(t for t, _ in row) for _, rows in p.example() for row in rows}
                self.assertEqual("ALERT    column 07" in shown, subnet <= 2, (subnet, seed))
                self.assertEqual("ALERT    4th byte after the pattern" in shown, subnet > 2, (subnet, seed))
                self.assertNotIn("hint", {s for _, rows in p.example() for row in rows for _, s in row}, (subnet, seed))

    def test_ids_targets_rise_with_level(self):
        first, last = at(1, HOPS + 1), at(runmod.SUBNETS, HOPS + 1)
        self.assertEqual((step(first, AlertLog.TARGETS), step(last, AlertLog.TARGETS)), (2, 5))
        self.assertLess(len(self.ids("RAW", 1, 0).targets), len(self.ids("RAW", runmod.SUBNETS, 0).targets))

    def test_ids_tools(self):
        """SCANNER flashes an armed entry about you; BRUTEFORCE clears one, and
        the known solution still goes through after it."""
        for seed in range(40):
            p = self.ids("PROTOCOL", 1 + seed % runmod.SUBNETS, seed)
            self.assertTrue(p.scan())
            [j] = list(p.flash)
            self.assertIn(j, [p.offset(e, "alert") for e in p.left()], seed)
            before = len(p.left())
            self.assertTrue(p.bruteforce())
            self.assertEqual(len(p.left()), before - 1, seed)
            self.assertEqual(p.broken(), [], seed)
            apply_actions(p, p.solution_actions())
            self.assertEqual((p.solved, p.mistakes), (True, 0), seed)
            self.assertFalse(p.scan() or p.bruteforce())        # nothing left to do once solved

    def test_ids_layout_wraps_from_the_third(self):
        """The first two IDS line an entry up with a row, ALERT last; from the
        third the fields are shuffled and rows no longer match entries."""
        for subnet in range(1, runmod.SUBNETS + 1):
            orders = set()
            for seed in range(40):
                p = self.ids("RAW", subnet, seed)
                orders.add(tuple(name for name, _ in p.fields))
                self.assertLessEqual(len(p.data), p.cols * AlertLog.WINDOW, (subnet, seed))
                if subnet <= 2:
                    self.assertEqual(p.cols, p.size, (subnet, seed))
                    self.assertEqual(p.fields[-1][0], "alert", (subnet, seed))
                else:
                    self.assertNotEqual(p.cols, p.size, (subnet, seed))
            self.assertEqual(len(orders) > 2, subnet >= 3, (subnet, orders))

    def test_ids_decoys(self):
        """From the second IDS: entries with your address in DEST, and one whose
        source is a byte off yours. Editing them is a near miss; the rest is worse."""
        for subnet in range(1, runmod.SUBNETS + 1):
            for seed in range(40):
                p = self.ids("PROTOCOL", subnet, seed)
                where = (subnet, seed)
                kinds = set(p.decoys.values())
                self.assertEqual(kinds, set() if subnet == 1 else {"near", "dest"}, where)
                for e in range(p.count):
                    src = bytes(p.entry(e)[p.offsets["source"]:p.offsets["source"] + 4])
                    diff = sum(a != b for a, b in zip(src, p.yours))
                    if e in p.targets:
                        self.assertEqual(diff, 0, where)
                    elif p.decoys.get(e) == "near":
                        self.assertEqual(diff, 1, where)
                    else:
                        self.assertGreaterEqual(diff, 2, where)
                plain = next(e for e in range(p.count) if e not in p.targets and e not in p.decoys
                             and p.data[p.offset(e, "alert")] == 1)
                self.assertEqual(apply_actions(p, [("click", p.offset(plain, "alert")), ("type", "00")])[-1],
                                 "mistake")
                self.assertEqual(p.severity, puzzles.WRONG, where)
                self.assertEqual(p.data, bytearray(p.original), where)      # a mistake writes nothing
                for e, kind in p.decoys.items():
                    apply_actions(p, [("click", p.offset(e, "alert")), ("type", "00")])
                    self.assertEqual(p.severity, puzzles.NEAR, where)
                other = p.offset(p.targets[0], "port")
                apply_actions(p, [("click", other), ("type", "%02x" % (p.data[other] ^ 0x55))])
                self.assertEqual(p.severity, puzzles.WILD, where)
                t = p.offset(p.targets[0], "alert")
                self.assertEqual(apply_actions(p, [("click", t), ("type", "ff")])[-1], "mistake", where)
                self.assertEqual(p.severity, puzzles.WRONG, where)
                self.assertEqual(apply_actions(p, [("click", t), ("type", "00")])[-1], "ok", where)
                before = p.mistakes
                self.assertIsNone(apply_actions(p, [("click", t), ("type", "00")])[-1], where)    # already 00
                self.assertEqual(p.mistakes, before, where)

    def test_payload_says_the_next_byte(self):
        """The panel says what the sequence being spelled needs next. The end
        of the buffer counts: a byte two sequences share is picked once."""
        from puzzles.payload import Payload
        p = Payload(0, 1)
        p.rows = p.cols = 5
        p.data = bytearray(bytes.fromhex("9D64A1642F" "8A8AA19D2F" "2F648A9D8A" "648A8A8A8A" "9D8AA1642F"))
        p.targets = [bytes.fromhex(t) for t in ("2F2F", "2FA18A", "8A648A9D")]
        p.buffer_size, p.picks, p.wild_next = 9, [], False
        self.assertEqual(p.next_byte(), 0x2F)
        self.assertEqual(apply_actions(p, [("click", 4), ("click", 24)]), ["ok", "ok"])    # 2F 2F
        self.assertEqual(p.done(), [True, False, False])
        self.assertEqual(p.next_byte(), 0xA1)                   # the second 2F starts 2F A1 8A: no new 2F is needed
        self.assertIn(("NEXT BYTE: A1", "amber"), p.panel())
        route = [22, 12, 11, 6, 8]                              # A1 8A 64 8A 9D
        for i, idx in enumerate(route):
            self.assertEqual(p.next_byte(), p.data[idx], i)
            self.assertEqual(p.click(idx), "solved" if idx == route[-1] else "ok", i)
        self.assertEqual((p.done(), p.rank[0]), ([True] * 3, "DEEP BREACH"))
        self.assertFalse(any(row[0].startswith("NEXT BYTE") for row in p.panel()))
        # a pick that is no part of the sequence: it starts again from its first byte
        p.solved, p.rank, p.picks = False, None, [(4, False), (24, False)]
        p.click(20)                                             # 9D
        self.assertEqual(p.next_byte(), 0x2F)
        # on every node, the line names a byte of the first sequence still to spell, until all are in
        for seed in range(SEEDS):
            p = REGISTRY["PAYLOAD"].generate(seed, source("RAW"), level_for(seed))
            self.assertEqual(p.next_byte(), p.targets[0][0], seed)
            for idx in p.solution[:-1]:
                p.click(idx)
                todo = next(t for t, ok in zip(p.targets, p.done()) if not ok)
                self.assertIn(p.next_byte(), todo, seed)
                self.assertTrue(all(len(row[0]) <= 41 for row in p.panel()), seed)

    def test_ids_find_is_a_hunt(self):
        """The first step is a HUNT for the address: a click on a copy in SOURCE
        marks it and moves the steps on. A copy in DEST, a source a byte off or
        any other address is a mistake."""
        from puzzles.base import hexs

        def now(p):
            return next(text for text, state in p.tasks() if state == "now")

        def clear(p, e):
            """Set an entry's ALERT byte to 00, and put its CHECK byte right where there is one."""
            edits = [(p.offset(e, "alert"), 0)]
            if p.has_check:
                edits.append((p.offset(e, "check"), p.original[p.offset(e, "check")] ^ 1))
            return apply_actions(p, [a for idx, v in edits for a in (("click", idx), ("type", "%02x" % v))])[-1]

        for subnet in range(1, runmod.SUBNETS + 1):
            for seed in range(30):
                p = self.ids("PROTOCOL", subnet, seed)
                where, k = (subnet, seed), len(p.targets)
                field = " in SOURCE" if subnet > 1 else ""          # which field counts, once there are decoys
                self.assertEqual(now(p), "Find %s%s (0/%d)" % (hexs(p.yours), field, k), where)
                self.assertFalse(any("yours" in text.lower() for text, _ in p.tasks()), where)
                self.assertFalse(any("yours" in row[0].lower() for row in p.panel()), where)
                first = p.targets[0]
                at_source = p.offset(first, "source")
                self.assertEqual(p.styles(), {}, where)                     # nothing is marked before a find
                self.assertEqual(p.click(at_source + 2), "ok", where)       # any byte of the copy
                # the find marks the copy and nothing else: where its ALERT byte is comes from the key
                self.assertEqual(p.styles(), dict.fromkeys(range(at_source, at_source + 4), "found"), where)
                self.assertEqual(now(p), "Set its ALERT byte to 00 (0/%d)" % k, where)      # it moved on
                self.assertIn("Find %s%s (1/%d)" % (hexs(p.yours), field, k), [t for t, _ in p.tasks()], where)
                self.assertIsNone(p.click(at_source), where)                # found already: nothing more
                self.assertEqual(p.mistakes, 0, where)
                self.tasks_ok(p, where)
                # cleared: back to the first step for the next copy
                self.assertEqual(clear(p, first), "ok", where)
                self.assertEqual(now(p), "Find %s%s (1/%d)" % (hexs(p.yours), field, k), where)
                # an alert cleared without a click on its copy counts as found
                self.assertEqual(clear(p, p.targets[1]), "ok", where)
                self.assertEqual(len(p.found), 2, where)
                for e, kind in p.decoys.items():
                    self.assertEqual(p.click(p.offset(e, "dest" if kind == "dest" else "source")), "mistake", where)
                    self.assertEqual(p.severity, puzzles.NEAR, where)
                plain = next(e for e in range(p.count) if e not in p.targets and e not in p.decoys)
                for name in ("source", "dest"):
                    self.assertEqual(p.click(p.offset(plain, name)), "mistake", where)
                    self.assertEqual(p.severity, puzzles.WRONG, where)
                self.assertEqual(len(p.found), 2, where)
                # the rest still goes through
                before = p.mistakes
                apply_actions(p, p.solution_actions())
                self.assertEqual((p.solved, p.mistakes), (True, before), where)
                self.tasks_ok(p, where)

    def test_ids_checks(self):
        """From the fourth IDS every entry carries a CHECK byte, the XOR of its
        other bytes; clearing an alert breaks it, so it has to be put right too."""
        for subnet in range(1, runmod.SUBNETS + 1):
            for seed in range(30):
                p = self.ids("RAW", subnet, seed)
                self.assertEqual(p.has_check, subnet >= 4, (subnet, seed))
                if not p.has_check:
                    continue
                self.assertEqual(p.broken(), [], (subnet, seed))
                alerts = [("click", p.offset(e, "alert")) for e in p.targets]
                apply_actions(p, [a for click in alerts for a in (click, ("type", "00"))])
                self.assertEqual(p.broken(), p.targets, (subnet, seed))
                # a broken CHECK byte is not marked in the dump: the key says where it is
                self.assertFalse({p.offset(e, "check") for e in p.targets} & set(p.styles()), (subnet, seed))
                self.assertEqual(p.key("enter"), "mistake")
                self.assertIn("fails its check" if len(p.targets) == 1 else "fail", p.messages[-1][0])
                c = p.offset(p.targets[0], "check")
                right = p.original[c] ^ 1
                apply_actions(p, [("click", c), ("type", "%02x" % (right ^ 0x10))])
                self.assertEqual(p.severity, puzzles.NEAR, (subnet, seed))
                self.assertEqual(apply_actions(p, [("click", c), ("type", "%02x" % right)])[-1], "ok")
                untouched = next(e for e in range(p.count) if e not in p.targets)
                apply_actions(p, [("click", p.offset(untouched, "check")), ("type", "%02x" % (
                    p.data[p.offset(untouched, "check")] ^ 1))])
                self.assertEqual(p.severity, puzzles.WRONG, (subnet, seed))
                for e in p.targets[1:]:
                    c = p.offset(e, "check")
                    apply_actions(p, [("click", c), ("type", "%02x" % (p.original[c] ^ 1))])
                self.assertEqual(p.key("enter"), "solved")

    def test_ids_enter(self):
        """Committing with something left is a mistake: a near miss with one thing, worse with more."""
        for seed in range(30):
            p = self.ids("PROTOCOL", 1, seed)
            self.assertEqual(p.key("enter"), "mistake")
            self.assertEqual(p.severity, puzzles.WRONG)
            [j] = list(p.flash)
            self.assertIn(j, [p.offset(e, "alert") for e in p.targets])
            a, b = p.targets
            apply_actions(p, [("click", p.offset(a, "alert")), ("type", "00")])
            self.assertEqual(p.key("enter"), "mistake")
            self.assertEqual(p.severity, puzzles.NEAR)
            apply_actions(p, [("click", p.offset(b, "alert")), ("type", "00")])
            self.assertEqual(p.key("enter"), "solved")


def _add(mode, kind):
    def test(self):
        self.check(mode, kind)
    setattr(SolvableTest, "test_%s_%s" % (mode.lower(), kind.lower()), test)


for _mode in ("RAW", "PROTOCOL", "LIVE"):
    for _kind in ("PAYLOAD", "HUNT", "XOR", "CARVE", "REASSEMBLE") + (() if _mode == "RAW" else ("DISSECT", "CHECKSUM")):
        _add(_mode, _kind)


class RulesTest(unittest.TestCase):
    """The validators reject wrong answers, and mistakes are counted."""

    def test_same_seed_same_puzzle(self):
        for mode in ("RAW", "PROTOCOL"):
            for kind in kinds_for_mode(mode):
                a = REGISTRY[kind].generate(123, source(mode), 3)
                b = REGISTRY[kind].generate(123, source(mode), 3)
                self.assertEqual((bytes(a.data), a.solution), (bytes(b.data), b.solution), kind)

    def test_payload_rules(self):
        for seed in range(200):
            p = REGISTRY["PAYLOAD"].generate(seed, source("RAW"), level_for(seed))
            sol, c = p.solution, p.cols
            self.assertLess(sol[0], c)                          # starts in the top row
            for n, (a, b) in enumerate(zip(sol, sol[1:])):
                if n % 2 == 0:
                    self.assertEqual(a % c, b % c)              # then same column
                else:
                    self.assertEqual(a // c, b // c)            # then same row
            self.assertFalse(p.validate([]))
            self.assertFalse(p.validate([sol[0], sol[0]]))      # no reuse
            self.assertFalse(p.validate(list(sol) + [10 ** 6]))
            bottom = next(i for i in range(c, len(p.data)) if i % c != sol[0] % c)
            self.assertFalse(p.validate([bottom]))              # not in the top row
            self.assertIsNone(p.click(bottom))                  # refused, and no penalty
            self.assertEqual(p.mistakes, 0)

    def test_payload_overflow_flushes_and_costs(self):
        p = REGISTRY["PAYLOAD"].generate(5, source("PROTOCOL"), 2)
        results = []
        for _ in range(p.buffer_size * 3):
            if p.solved:
                break
            results.append(p.click(p.allowed()[-1]))
        if not p.solved:
            self.assertIn("mistake", results)
            self.assertLess(len(p.picks), p.buffer_size)

    def test_payload_tools(self):
        p = REGISTRY["PAYLOAD"].generate(8, source("RAW"), 3)
        self.assertTrue(p.bruteforce())
        self.assertFalse(p.bruteforce())                          # already armed
        p.click(p.allowed()[0])
        self.assertEqual(p._buffer(p.picks), [None])
        self.assertTrue(p.snapshot())
        self.assertEqual(p.picks, [])
        self.assertFalse(p.snapshot())
        self.assertTrue(p.scan())
        self.assertIn(p.solution[0], p.flash)

    def test_hunt(self):
        for seed in range(200):
            p = REGISTRY["HUNT"].generate(seed, source("PROTOCOL"), level_for(seed))
            self.assertEqual(find_all(p.data, p.pattern), p.solution)
            self.assertGreaterEqual(len(p.solution), 2)
            self.assertFalse(p.validate(p.solution[:-1]))
            self.assertFalse(p.validate(p.solution + [len(p.data) - 1]))
            taken = {s + j for s in p.solution for j in range(len(p.pattern))}
            miss = next(i for i in range(len(p.data)) if i not in taken)
            self.assertEqual(p.click(miss), "mistake")
            self.assertEqual(p.click(p.solution[0] + len(p.pattern) - 1), "ok")   # any byte of it counts
            self.assertIsNone(p.click(p.solution[0]))                             # already found

    def test_xor(self):
        for mode in ("RAW", "PROTOCOL"):
            for seed in range(200):
                p = REGISTRY["XOR"].generate(seed, source(mode), level_for(seed))
                key = p.solution
                self.assertEqual(len(key), p.keylen)
                self.assertNotIn(0, key)
                self.assertNotEqual(bytes(p.cipher), bytes(p.plain))
                # the hint is real plaintext and lines up with the key
                self.assertEqual(p.hint_off % p.keylen, 0)
                self.assertEqual(bytes(p.plain[p.hint_off:p.hint_off + len(p.hint)]), p.hint)
                for i in range(p.keylen):
                    self.assertEqual(p.cipher[p.hint_off + i] ^ p.hint[i], key[i])
                wrong = bytes([key[0] ^ 0x01]) + key[1:]
                self.assertFalse(p.validate(wrong))
                self.assertFalse(p.validate(b""))
                p.click(p.hint_off)                               # a pattern to find is found
                apply_actions(p, [("type", p.typing(wrong))])
                self.assertEqual(p.key("enter"), "mistake")
                self.assertTrue(p.bruteforce())                   # reveals k0
                self.assertEqual(p.locked, {0: key[0]})
                apply_actions(p, [("type", p.typing(key))])
                if p.double:                                      # the first key uncovers a second
                    self.assertEqual(p.key("enter"), "ok")
                    p.click(p.hint_off)
                    apply_actions(p, [("type", p.typing(p.solution))])
                self.assertEqual(p.key("enter"), "solved")
                self.assertEqual(bytes(p.display()), bytes(p.plain))

    def test_xor_has_four_levels_climbed_one_solved_xor_at_a_time(self):
        """A run's first XOR is level 1, its second 2, its third 3, and each
        one after that is 3 or 4, wherever in the run it is met. (A double XOR
        goes by a rule of its own: see its test.)"""
        xor = REGISTRY["XOR"]
        for mode in ("RAW", "PROTOCOL"):
            later = set()
            for seed in range(120):
                level = level_for(seed)
                where = (mode, seed)
                for solved, want in ((0, 1), (1, 2), (2, 3)):
                    self.assertEqual(xor.generate(seed, source(mode), level, solved).xor_level, want, where)
                for solved in (3, 4, 9):
                    p = xor.generate(seed, source(mode), level, solved)
                    if p.double:
                        continue
                    self.assertIn(p.xor_level, (3, 4), where)
                    later.add(p.xor_level)
                    self.assertIn(("XOR LEVEL", "%d of 4" % p.xor_level), p.brief(), where)
            self.assertEqual(later, {3, 4}, mode)
        for seed in range(60):
            for solved, (sizes, text) in enumerate(xor.LEVELS):
                p = next(q for s in range(seed, seed + 40) for q in [xor.generate(s, source("RAW"), 3, solved)]
                         if q.xor_level == solved + 1 and not q.double)
                known = [p.plain[o] for o in p.known]
                self.assertIn(p.keylen, sizes, (seed, solved))
                if text:                    # every key byte has to be worked out
                    self.assertTrue(all(32 <= b < 127 for b in known), (seed, solved))
                else:                       # the key shows through the zeros
                    self.assertEqual(known, [0] * p.keylen, (seed, solved))
                    self.assertEqual(bytes(p.cipher[o] for o in p.known), p.solution, (seed, solved))
                # in a packet the known bytes are its own, so a level is a key length there;
                # a key byte is read off a 00 whenever one lines up with it
                p = next(q for s in range(seed, seed + 40) for q in [xor.generate(s, source("PROTOCOL"), 3, solved)]
                         if q.xor_level == solved + 1 and not q.double)
                self.assertEqual(p.keylen, solved + 1, (seed, solved))
                for i, o in enumerate(p.known):
                    lined = [p.hint_off + j for j in range(len(p.hint)) if j % p.keylen == i]
                    self.assertIn(o, lined, (seed, solved))
                    self.assertEqual(p.cipher[o] ^ p.plain[o], p.solution[i], (seed, solved))
                    self.assertEqual(p.plain[o] == 0, 0 in [p.plain[x] for x in lined], (seed, solved))
        self.assertEqual(xor.generate(1, source("PROTOCOL"), 3, 0).tasks()[0][0][-6:], "XOR 00")
        # with no run to ask (practice), it goes by the level
        got = [xor.generate(5, source("RAW"), level).xor_level for level in (at(2), at(2, 4), at(3))]
        self.assertEqual(got, [1, 2, 3])
        self.assertEqual({p.xor_level for s in range(30) for p in [xor.generate(s, source("RAW"), at(5))]
                          if not p.double}, {3, 4})

    def test_xor_over_zeros_has_a_pattern_to_find_first(self):
        """Over zero padding the key repeats in plain sight. Nothing marks it
        and nothing names its bytes until it is clicked. Known text, and a
        packet's known bytes, are no pattern: those are marked from the start."""
        xor = REGISTRY["XOR"]
        patterns = set()
        for seed in range(80):
            for solved in range(5):
                where = (seed, solved)
                p = xor.generate(seed, source("PROTOCOL"), 3, solved)
                self.assertTrue(p.found and not any(s.find for s in p.stages), where)
                p = xor.generate(seed, source("RAW"), at(2 + seed % 4), solved)
                for stage in p.stages:
                    self.assertEqual(stage.find, not any(stage.hint), where)
                    size, n = (len(stage.hint), len(stage.key)) if stage.find else (8, len(stage.key))
                    # known bytes sit in one row of the dump, and start where the key starts
                    self.assertLessEqual(stage.off % p.cols + size, p.cols, where)
                    self.assertEqual(stage.off % n, 0, where)
                    if stage.find:      # the pattern: the key, a few times over
                        lo, hi = xor.REPEATS[n]
                        self.assertIn(size, range(n * lo, n * hi + 1, n), where)
                        self.assertEqual(bytes(stage.cipher[stage.off:stage.off + size]), stage.key * (size // n), where)
                        patterns.add((stage.level, n, size) if not p.double else None)
                first = p.stages[0]
                if not first.find:                  # known text: marked, and its place given
                    self.assertTrue(p.found and p.styles(), where)
                    self.assertIn("at 0x%04X" % p.hint_off, dict(p.brief())["KNOWN"], where)
                    self.assertIsNone(p.click(0), where)
                    continue
                size = len(p.hint)
                run = range(p.hint_off, p.hint_off + size)
                self.assertEqual((p.found, p.styles()), (False, {}), where)
                # nothing says where it is, or what its bytes are
                said = " ".join(text for text, _ in p.tasks()) + " ".join(text for _, text in p.brief())
                self.assertNotIn("0x", said, where)
                self.assertNotIn("%02X" % p.cipher[p.hint_off], said, where)
                find = "Find %d bytes where the key repeats" % size
                self.assertEqual([t for t, _ in p.tasks()][:3], [find, "Type the key", "Press ENTER to submit the key"],
                                 where)
                self.assertTrue(dict(p.brief())["KNOWN"].startswith("%d bytes of zero padding to find" % size), where)
                self.assertEqual(p.solution_actions()[0], ("click", p.hint_off), where)
                # the key cannot be typed before the pattern is found
                apply_actions(p, [("type", p.typing(p.solution)), ("key", "enter")])
                self.assertEqual((p.typed, p.solved, p.mistakes), ("", False, 0), where)
                # a click that misses costs TRACE: less when it is right beside the pattern
                beside = run[0] - 1 if run[0] else run[-1] + 1
                far = (run[0] + len(p.data) // 2) % len(p.data)
                if not any(s is not first and s.off <= far < s.off + len(s.hint) for s in p.stages) and p.plain[far]:
                    self.assertEqual((p.click(far), p.severity), ("mistake", puzzles.WRONG), where)
                if p.plain[beside]:                 # (a stray 00 beside the padding is part of the pattern)
                    self.assertEqual((p.click(beside), p.severity, p.found), ("mistake", puzzles.NEAR, False), where)
                # any byte of the pattern finds it: then it is marked, and the steps name its bytes
                self.assertEqual(p.click(run[seed % size]), "ok", where)
                self.assertEqual(sorted(p.styles()), list(run), where)
                self.assertEqual(p.tasks()[:2], [(find, "done"), ("Type k0 = %02X XOR 00" % p.solution[0], "now")], where)
                self.assertIsNone(p.click(far), where)      # found: clicks do nothing more
                # the tools: SCANNER finds the pattern, then a key byte; BRUTEFORCE a key byte, and the pattern with it
                q = xor.generate(seed, source("RAW"), at(2 + seed % 4), solved)
                self.assertTrue(q.scan())
                self.assertEqual((q.found, q.locked), (True, {}), where)
                self.assertTrue(q.scan())
                self.assertEqual(q.locked, {0: q.solution[0]}, where)
                q = xor.generate(seed, source("RAW"), at(2 + seed % 4), solved)
                self.assertTrue(q.bruteforce())
                self.assertEqual((q.found, q.locked), (True, {0: q.solution[0]}), where)
        # the pattern is not always as long, nor the key: every length each level has turns up
        self.assertEqual(patterns - {None}, {(1, 1, size) for size in range(4, 9)} | {(2, 2, 6), (2, 2, 8), (2, 2, 10),
                                                                                 (2, 3, 9), (2, 3, 12)})

    def test_a_double_xor_has_a_second_key_under_the_first(self):
        """Now and then, once a run has climbed the three steps, a dump is
        encrypted twice: the first key found uncovers the known bytes of a
        second. It is rare, each key has an XOR level of its own, and both are
        level 4 only in the final subnet."""
        xor = REGISTRY["XOR"]
        self.assertEqual(xor.DOUBLE_TOP, at(runmod.SUBNETS))
        for mode in ("RAW", "PROTOCOL"):
            doubles, pairs = 0, {False: set(), True: set()}
            for seed in range(600):
                level = at(2 + seed % 4, 1 + seed % HOPS)
                where = (mode, seed, level)
                for solved in range(3):         # never one of a run's first three
                    self.assertFalse(xor.generate(seed, source(mode), level, solved).double, where)
                p = xor.generate(seed, source(mode), level, 3 + seed % 3)
                if not p.double:
                    self.assertEqual((p.difficulty(), p.time_limit), (1.0, round(ramp(level, xor.TIME))), where)
                    continue
                doubles += 1
                first, second = p.stages
                final = bytes(second.plain)
                pairs[level >= xor.DOUBLE_TOP].add((first.level, second.level))
                self.assertTrue(len(first.key) <= 2 and len(second.key) <= 2, where)      # so the steps fit the list
                # more time, more pay, and the briefing says there are two
                self.assertEqual((p.difficulty(), p.time_limit), (1.5, round(ramp(level, xor.TIME) * 1.5)), where)
                rows = dict(p.brief())
                self.assertEqual(rows["DO"], "Work out two keys, one after the other.", where)
                self.assertEqual(rows["XOR LEVEL"], "%d of 4, then %d of 4" % (first.level, second.level), where)
                self.assertTrue(rows["KNOWN"].endswith(", for the first key"), where)
                self.assertEqual(p.tasks()[-1], ("Then do the same for a second key", "todo"), where)
                if first.find and second.find:      # two patterns in the dump: the wrong one costs nothing
                    self.assertEqual((p.click(second.off), p.mistakes, p.found), (None, 0, False), where)
                p.click(p.hint_off)
                # the second key covers a block that the first key's known bytes are outside of
                lo, hi = second.span
                self.assertEqual(first.span, (0, len(final)), where)
                self.assertTrue(0 <= lo < hi <= len(final) and hi - lo < len(final), where)
                self.assertFalse(any(lo <= o < hi for o in first.known), where)
                self.assertTrue(all(lo <= o < hi for o in second.known), where)
                # until the first key is in, the second one's known bytes show nothing of its key
                for i, o in enumerate(second.known):
                    self.assertNotEqual(p.data[o] ^ final[o], second.key[i], where)
                apply_actions(p, [("type", p.typing(p.solution))])
                self.assertEqual((p.key("enter"), p.solved, p.mistakes), ("ok", False, 0), where)
                # the first key is in: all but the block reads true, and the second key's known bytes light up
                shown = bytes(p.display())
                self.assertEqual(shown[:lo] + shown[hi:], final[:lo] + final[hi:], where)
                self.assertNotEqual(shown[lo:hi], final[lo:hi], where)
                self.assertEqual((p.solution, p.xor_level), (second.key, second.level), where)
                self.assertEqual(p.tasks()[0], ("Work out the first key", "done"), where)
                if second.find:                     # a new pattern, and it is to be found like the first
                    self.assertEqual((p.found, p.styles()), (False, {}), where)
                    if first.find:                  # the first key's zeros read as zeros now: not it
                        self.assertEqual((p.click(first.off), p.mistakes), (None, 0), where)
                    self.assertEqual(p.click(second.off + 3), "ok", where)
                self.assertEqual(sorted(i for i, st in p.styles().items() if st == "flash"),
                                 list(range(second.off, second.off + len(second.hint))), where)
                for i, o in enumerate(p.known):
                    self.assertEqual(shown[o] ^ final[o], second.key[i], where)
                # a wrong second key costs a mistake, and the first is not asked for again
                wrong = bytes(b ^ 0xFF for b in second.key)
                apply_actions(p, [("type", p.typing(wrong))])
                self.assertEqual((p.key("enter"), p.stage, p.found), ("mistake", 1, True), where)
                self.assertTrue(p.bruteforce())
                self.assertEqual(p.locked, {0: second.key[0]}, where)
                apply_actions(p, [("type", p.typing(second.key))])
                self.assertEqual(p.key("enter"), "solved", where)
                self.assertEqual(bytes(p.display()), final, where)
            self.assertTrue(0.1 < doubles / 600 < 0.3, (mode, doubles))         # sparingly
            top = 4 if mode == "RAW" else 2         # a packet gives each key two known bytes: 1 or 2 bytes
            for final_subnet, seen in pairs.items():
                self.assertTrue(all(1 <= a <= top and 1 <= b <= top for a, b in seen), (mode, seen))
            self.assertNotIn((4, 4), pairs[False], mode)
        # both keys at level 4: in the final subnet, and only there
        last = {tuple(s.level for s in p.stages) for seed in range(1500)
                for p in [xor.generate(seed, source("RAW"), at(runmod.SUBNETS, 1 + seed % HOPS), 3)] if p.double}
        self.assertEqual(last, {(a, b) for a in range(1, 5) for b in range(1, 5)})
        before = {tuple(s.level for s in p.stages) for seed in range(1500)
                  for p in [xor.generate(seed, source("RAW"), at(runmod.SUBNETS - 1, 1 + seed % HOPS), 3)] if p.double}
        self.assertEqual(before, {(a, b) for a in range(1, 5) for b in range(1, 5)} - {(4, 4)})

    def test_the_side_panel_holds_only_what_the_puzzle_cannot_be_solved_without(self):
        """XOR: the key so far, and the working only for a key byte that has
        to be worked out, which is typed as its bits. IDS: where the fields the
        steps name are, and the byte being edited. No tables beyond that, and
        no instructions."""
        xor = REGISTRY["XOR"]
        for seed in range(40):
            for mode in ("RAW", "PROTOCOL"):
                for solved in range(5):
                    p = xor.generate(seed, source(mode), 3, solved)
                    for stage in p.stages:      # a double XOR: the same again for its second key
                        p.click(p.hint_off)     # a pattern to find is found
                        for i in range(p.keylen):
                            rows = [row[0] for row in p.panel()]
                            self.assertTrue(rows[0].startswith("KEY > "), rows)
                            c, pl = p.cipher[p.known[i]], p.plain[p.known[i]]
                            task = next(text for text, state in p.tasks() if state == "now")
                            if pl == 0:             # the key shows through: nothing to work out, typed as hex
                                self.assertEqual(len(rows), 1, (seed, mode, solved, rows))
                                self.assertEqual(task, "Type k%d = %02X XOR 00" % (i, c))
                                apply_actions(p, [("type", "%02x" % p.solution[i])])
                                continue
                            self.assertEqual(task, "Type the bits of k%d = %02X XOR %02X" % (i, c, pl))
                            self.assertEqual(rows[1:], ["", "  %02X = %s" % (c, bits(c)), "  %02X = %s" % (pl, bits(pl)),
                                                        "  k%d = ____ ____" % i])
                            want = format(p.solution[i], "08b")
                            before = p.typed
                            for ch in "2af":        # only a bit goes in
                                self.assertIsNone(p.key(ch))
                            self.assertEqual(p.typed, before)
                            apply_actions(p, [("type", want[:4])])      # four bits typed: their hex digit shows
                            self.assertEqual(p.panel()[-1][0], "  k%d = %s ____" % (i, want[:4]))
                            self.assertEqual(p.panel()[0][0].split()[2 + i], "%X_" % (p.solution[i] >> 4))
                            apply_actions(p, [("type", want[4:])])
                            self.assertEqual(p.panel()[0][0].split()[2 + i], "%02X" % p.solution[i])
                            self.assertEqual(p.key_bytes()[i], p.solution[i])
                        self.assertEqual(p.key("enter"), "solved" if stage is p.stages[-1] else "ok")
                    self.assertEqual(len(p.panel()), 1)
        for subnet in range(1, runmod.SUBNETS + 1):
            for seed in range(20):
                p = puzzles.ids.generate(seed, source("RAW"), at(subnet, HOPS + 1))
                ids_key_ok(self, p, (subnet, seed))
                rows = [row[0] for row in p.panel()]
                p.click(p.offset(p.targets[0], "alert"))
                p.key("0")
                self.assertEqual([row[0] for row in p.panel()][len(rows):],
                                 ["", "EDIT > 0x%04X: 01 -> 0_" % p.offset(p.targets[0], "alert")])

    def test_dissect(self):
        for mode in ("PROTOCOL", "LIVE"):
            for seed in range(200):
                p = REGISTRY["DISSECT"].generate(seed, source(mode), level_for(seed))
                self.assertEqual(len(set(f.name for f in p.fields)), len(p.fields))
                lo, hi = p.solution[0]
                self.assertEqual(p.select(lo, hi + 1), "mistake")
                self.assertEqual(p.round, 0)
                self.assertFalse(p.validate(p.solution[::-1]) and len(p.solution) > 1 and
                                 p.solution != p.solution[::-1])
                self.assertFalse(p.validate(p.solution[:-1]))
                self.assertIn(p.select(lo, hi), ("ok", "solved"))
                self.assertEqual(p.learned[0][:2], ("field", p.fields[0].name))

    def test_dissect_levels_gate_protocols(self):
        for seed in range(300):
            p = REGISTRY["DISSECT"].generate(seed, source("PROTOCOL"), 1)
            self.assertTrue({f.layer for f in p.fields} <= {"Ethernet", "IPv4"}, seed)
            p = REGISTRY["DISSECT"].generate(seed, source("PROTOCOL"), 2)
            self.assertTrue({f.layer for f in p.fields} <= {"Ethernet", "IPv4", "TCP", "UDP"}, seed)
        layers = set()
        for seed in range(300):
            layers |= {f.layer for f in REGISTRY["DISSECT"].generate(seed, source("PROTOCOL"), 5).fields}
        self.assertTrue({"DNS", "HTTP"} <= layers)

    def test_checksum(self):
        targets = set()
        for mode in ("PROTOCOL", "LIVE"):
            for seed in range(300):
                p = REGISTRY["CHECKSUM"].generate(seed, source(mode), level_for(seed))
                targets.add(p.target)
                off, good = p.solution
                self.assertNotEqual(p.current_sum(), 0xFFFF)
                self.assertNotEqual(p.data[off], good)
                self.assertTrue(p.cover[0] <= off < p.cover[1])
                self.assertFalse(p.validate((off, p.data[off])))
                self.assertFalse(p.validate((len(p.data), 0)))
                bad = next(v for v in range(256) if v != p.data[off] and not p.validate((off, v)))
                self.assertIsNone(p.click(off))
                self.assertEqual(apply_actions(p, [("type", "%02x" % bad)])[-1], "mistake")
                self.assertNotEqual(p.current_sum(), 0xFFFF)    # a failed edit is not kept
                self.assertEqual(apply_actions(p, [("type", "%02x" % good)])[-1], "solved")
                self.assertEqual(p.current_sum(), 0xFFFF)
                self.assertEqual(p.error_text(), "none")
        self.assertEqual(targets, {"IPv4", "TCP", "UDP"})

    def test_checksum_error_readout(self):
        """ERROR names the wrong byte's excess, whichever byte and however big: the sum wraps, the readout must not."""
        big = 0
        for seed in range(400):
            p = REGISTRY["CHECKSUM"].generate(seed, source("PROTOCOL"), 1)
            off, good = p.solution
            delta = p.data[off] - good
            high = (off - p.ip_start) % 2 == 0
            if abs(delta) == 0xFF:
                continue            # FF too big in one byte reads the same as FF too small in its neighbour
            big += abs(delta) > 0x7F
            if high:
                delta *= 256
            want = "+0x%04X" % delta if delta > 0 else "-0x%04X" % -delta
            self.assertEqual(p.error_text(), want, seed)
            self.assertEqual(p.error(), delta, seed)
        self.assertGreater(big, 100)

    def test_carve(self):
        for mode in ("RAW", "PROTOCOL", "LIVE"):
            for seed in range(200):
                p = REGISTRY["CARVE"].generate(seed, source(mode), level_for(seed))
                self.assertEqual(signatures_in(p.data), p.files)             # nothing hidden by accident
                self.assertFalse(p.validate(p.files[:-1]))
                pos, name = p.files[0]
                other = next(n for n in p.pool if n != name)
                self.assertFalse(p.validate([(pos, other)] + p.files[1:]))
                for lo, hi in p.decoys:
                    self.assertEqual(p.click(lo), "mistake")
                self.assertEqual(p.click(pos), "ok")
                self.assertIsNone(p.click(pos + 1))                 # must identify first
                opts = p.options[0]
                self.assertEqual(sorted(opts), sorted(p.pool))       # every signature in play is a choice
                wrong = next(i for i, n in enumerate(opts) if n != name)
                self.assertEqual(p.key(str(wrong + 1)), "mistake")
                self.assertIn(p.key(str(opts.index(name) + 1)), ("ok", "solved"))

    def test_tasks_follow_the_player(self):
        """The current step moves with what the player has done, and back when an answer is rejected."""
        from puzzles.base import hexs

        def now(p):
            return next(text for text, state in p.tasks() if state == "now")

        src = source("PROTOCOL")
        p = next(q for s in range(100) for q in [REGISTRY["CARVE"].generate(s, src, at(3))] if len(q.files) > 1)
        self.assertEqual(now(p), "Find a file signature")
        pos, name = p.files[0]
        p.click(pos)
        self.assertEqual(now(p), "Name it: press 1-%d" % len(p.pool))
        p.key(str(p.options[0].index(name) + 1))
        self.assertEqual(now(p), "Find a file signature")        # back to the first step for the next file

        p = REGISTRY["HUNT"].generate(3, src, at(2))
        self.assertEqual(len(p.tasks()), 1)
        self.assertTrue(now(p).endswith("(0/%d)" % len(p.solution)), now(p))
        self.assertNotIn("click", now(p).lower())                # how to click is known by now
        p.click(p.solution[0])
        self.assertTrue(now(p).endswith("(1/%d)" % len(p.solution)), now(p))

        p = REGISTRY["XOR"].generate(3, src, at(2, 5))
        self.assertIn("k0 = ", now(p))
        apply_actions(p, [("type", p.typing(bytes(p.keylen)))])
        self.assertTrue(now(p).startswith("Press ENTER"))
        self.assertEqual(p.key("enter"), "mistake")
        self.assertIn("k0 = ", now(p))                           # the rejected key is cleared
        self.assertTrue(p.bruteforce())
        self.assertNotIn("k0 = ", now(p))                        # that byte is revealed, so done

        p = REGISTRY["PAYLOAD"].generate(3, src, at(1, 3))
        self.assertEqual([t for t, _ in p.tasks()], ["Spell " + hexs(t) for t in p.targets])   # no "pick from": the dump enforces that
        p.click(p.solution[0])
        self.assertEqual(now(p), "Spell " + hexs(p.targets[0]))

        p = REGISTRY["CHECKSUM"].generate(3, src, at(2, 4))
        self.assertTrue(now(p).startswith("Find"))
        p.click(p.solution[0])
        self.assertTrue(now(p).startswith("Type"))


class FairnessTest(unittest.TestCase):
    """No node is a giveaway, no route is a shortcut, and pay follows effort."""

    def routes(self, net):
        out = []

        def walk(node, acc):
            acc = acc + [node]
            if node.kind == "IDS":
                return out.append(acc)
            for i in node.next:
                walk(net.nodes[i], acc)

        for node in net.layer(0):
            walk(node, [])
        return out

    def test_maps_differ_and_hold_no_shops(self):
        for mode in ("RAW", "PROTOCOL"):
            shapes, footholds, passed = set(), set(), set()
            for seed in range(400):
                net = runmod.generate_subnet(random.Random(seed), 1 + seed % runmod.SUBNETS, source(mode))
                where = (mode, seed)
                hops = [net.layer(n) for n in range(runmod.LAYERS)]
                shapes.add(tuple(tuple(n.slot for n in hop) for hop in hops))
                # no shop is met on the way through: the shop opens when the IDS is down
                kinds = [n.kind for n in net.nodes.values()]
                self.assertNotIn("SHOP", kinds, where)
                # a foothold on the last hop, a breather before the IDS, and at most one more
                self.assertEqual(sum(n.kind == "FOOTHOLD" for n in hops[-1]), 1, where)
                self.assertIn(kinds.count("FOOTHOLD"), (1, 2), where)
                footholds.add(kinds.count("FOOTHOLD"))
                # none on the first hop, and the hops in between each keep a puzzle
                self.assertTrue(all(n.kind in REGISTRY for n in hops[0]), where)
                for hop in hops[:-1]:
                    self.assertTrue(any(n.kind in REGISTRY for n in hop), where)
                for route in self.routes(net):
                    passed.add(sum(n.kind == "FOOTHOLD" for n in route))
                # links never cross
                for layer in range(runmod.LAYERS - 1):
                    links = [(a.slot, net.nodes[i].slot) for a in hops[layer] for i in a.next]
                    self.assertFalse(any(a < c and b > d for a, b in links for c, d in links), where)
            self.assertEqual(footholds, {1, 2})
            self.assertEqual(passed, {0, 1, 2})     # whether a route passes a foothold is a choice
            self.assertGreater(len(shapes), 300)    # and no two maps look alike

    def test_pay_follows_difficulty(self):
        state = runmod.RunState("PROTOCOL", source("PROTOCOL"), 1)
        by_difficulty = sorted(REGISTRY, key=lambda kind: REGISTRY[kind].PAY)
        self.assertEqual(by_difficulty, ["HUNT", "CARVE", "DISSECT", "PAYLOAD", "XOR", "REASSEMBLE",
                                         "CHECKSUM"])
        before = None
        for _, _, level in run_levels():
            pay = [state.reward(kind, 0.5, level) for kind in by_difficulty]
            self.assertEqual(pay, sorted(set(pay)), level)              # a harder kind always pays more
            if before is not None:
                self.assertTrue(all(now >= then for now, then in zip(pay, before)), level)     # and so does a later node
            before = pay
            # a quick solve pays more than a slow one
            self.assertGreater(state.reward("HUNT", 1.0, level), state.reward("HUNT", 0.0, level))
            # and doing nothing at a foothold never beats doing a puzzle slowly
            self.assertLess(runmod.FOOTHOLD_CREDITS, min(state.reward(kind, 0.0, level) for kind in REGISTRY))

    def test_every_briefing_is_about_its_own_node(self):
        for mode in ("RAW", "PROTOCOL"):
            for kind in kinds_for_mode(mode):
                briefs = set()
                for seed in range(6):
                    for level in (max(REGISTRY[kind].first, 1.0), 3.5, 5.5):
                        p = puzzles.generate(kind, seed, source(mode), level)
                        if p.kind != kind:
                            continue                # fell back to a bytes-only puzzle
                        rows = p.brief()
                        self.assertTrue(p.what and p.summary() and rows, (mode, kind))
                        self.assertTrue(all(label and text for label, text in rows), (mode, kind))
                        briefs.add((p.summary(), tuple(rows)))
                        # and it is a glance, not a read: a few short rows, the first of them what to do
                        self.assertEqual(rows[0], ("DO", p.do), kind)
                        self.assertLessEqual(len(rows), 5, kind)
                        for label, text in rows:
                            self.assertLessEqual(len(label), 9, (kind, label))
                            self.assertLessEqual(len(text), 52, (kind, text))
                        # beside it, the job in miniature: a short loop of frames, each a few rows
                        # that fit where the side panel goes
                        example = p.example()
                        self.assertTrue(3 <= len(example) <= 12, kind)
                        self.assertLessEqual(sum(secs for secs, _ in example), 8, kind)
                        for secs, rows in example:
                            self.assertGreater(secs, 0, kind)
                            self.assertTrue(1 < len(rows) <= 5, kind)
                            for pieces in rows:
                                self.assertLessEqual(len("".join(text for text, _ in pieces)), 38, (kind, pieces))
                        self.assertNotEqual(example[0][1], example[-1][1], kind)        # something happens in it
                        marked = {style for _, rows in example for pieces in rows for _, style in pieces}
                        self.assertTrue(marked & {"sel", "found", "picked"}, kind)      # bytes picked out, as in the dump
                self.assertGreaterEqual(len(briefs), 3, (mode, kind))   # not the same text every time

    def test_an_example_shows_how_and_never_where(self):
        from puzzles.base import hexs
        for seed in range(40):
            p = REGISTRY["CARVE"].generate(seed, source("RAW"), level_for(seed))
            shown = "".join(text for _, rows in p.example() for pieces in rows for text, _ in pieces)
            for _, name in p.files:                                 # never a file that is on this node
                self.assertNotIn(hexs(puzzles.SIGNATURES[name][0]), shown, seed)
            p = REGISTRY["DISSECT"].generate(seed, source("PROTOCOL"), level_for(seed))
            asked = "".join(text for text, _ in p.example()[0][1][0])
            self.assertFalse(any(f.label in asked for f in p.fields), (seed, asked))     # nor a field it asks for
            p = REGISTRY["HUNT"].generate(seed, source("RAW"), level_for(seed))
            self.assertIn((hexs(p.pattern), "found"), p.example()[-1][1][0])            # the pattern, not its place

    def test_carve_marks_nothing_but_shows_how_signatures_read(self):
        from puzzles.base import hexs
        early = REGISTRY["CARVE"].generate(5, source("RAW"), 1)
        for level in (1, 2.5, 4):
            p = REGISTRY["CARVE"].generate(5, source("RAW"), level)
            self.assertEqual(p.styles(), {})                                              # no hint in the dump, ever
            self.assertFalse(any(label == "HELP" for label, _ in p.brief()))
        table = [row[0] for row in early.panel()]
        rows = {"ZIP": "  ZIP    50 4B 03 04  PK..",           # how a signature reads in the ASCII pane
                "EXE": "  EXE    4D 5A 90 00  MZ..",
                "JPEG": "  JPEG   FF D8 FF DB"}                 # nothing to read: just the bytes
        for name, row in rows.items():
            self.assertEqual(row in table, name in early.pool, name)
        self.assertTrue(all(len(row) <= 41 for row in table))

    def test_no_file_names_itself(self):
        import re
        from puzzles.base import printable
        for name, (signature, tail, desc, first) in puzzles.SIGNATURES.items():
            text = printable(signature + tail).lower()
            for word in re.findall(r"[a-z0-9]{3,}", (name + " " + desc).lower()):
                self.assertNotIn(word, text, name)                      # the ASCII pane does not print the answer
            self.assertGreaterEqual(len(signature), 3, name)
        for shown in puzzles.SELF_NAMING:                               # the ones that do are not in the game
            self.assertFalse(any(shown.encode("latin-1").startswith(sig[0]) or sig[0].startswith(shown.encode("latin-1"))
                                 for sig in puzzles.SIGNATURES.values()), shown)
        self.assertGreaterEqual(sum(sig[3] <= 1 for sig in puzzles.SIGNATURES.values()), 9)
        self.assertLessEqual(len(puzzles.SIGNATURES), 13)               # the table has to fit beside nine choices

    def test_carve_says_its_count_in_one_place(self):
        p = REGISTRY["CARVE"].generate(3, source("RAW"), 1)
        self.assertNotIn("/", p.prompt())                               # not in the prompt above the dump
        self.assertEqual(p.panel()[0][0], "FILES RECOVERED 0/1")       # only in the panel beside it

    def test_carve_offers_every_signature_in_play_and_always_shows_the_bytes(self):
        from puzzles.base import hexs
        for seed in range(300):
            p = REGISTRY["CARVE"].generate(seed, source("RAW"), level_for(seed))
            for (pos, name), opts in zip(p.files, p.options):
                self.assertEqual(sorted(opts), sorted(p.pool), seed)
                self.assertIn(len(opts), (4, 5, 6), seed)                   # a short list, not all of them
                self.assertIn(name, opts)
            table = [line[0] for line in p.panel()]
            for name in p.pool:
                self.assertTrue(any(hexs(puzzles.SIGNATURES[name][0]) in row for row in table), (seed, name))
            self.assertIn("1-%d" % len(p.pool), (p.click(p.files[0][0]), p.prompt())[1])
            rows = p.panel()
            self.assertEqual(sum(len(r) > 2 for r in rows), len(p.pool))    # one clickable answer each
            self.assertLessEqual(len(rows), 25)                         # and it all fits above the tools list
            for name in p.pool:                                         # the table is still there while choosing
                self.assertTrue(any(hexs(puzzles.SIGNATURES[name][0]) in r[0] for r in rows), (seed, name))
            self.assertIsNone(p.key("0"))
            right = p.options[0].index(p.files[0][1])
            wrong = next(k for k in range(9) if k != right)
            self.assertEqual(p.key(str(wrong + 1)), "mistake")
            self.assertIn(p.key(str(right + 1)), ("ok", "solved"))


class SeverityTest(unittest.TestCase):
    """A mistake costs TRACE by how bad it was: half for a near miss, double for a wild guess."""

    def test_cost_scales_with_severity(self):
        cost = runmod.RunState.mistake_cost
        self.assertEqual([cost(1, s) for s in (puzzles.NEAR, puzzles.WRONG, puzzles.WILD)], [1, 2, 4])
        self.assertEqual([cost(LAST, s) for s in (puzzles.NEAR, puzzles.WRONG, puzzles.WILD)], [5, 9, 18])
        self.assertEqual(cost(3.5), cost(3.5, puzzles.WRONG))
        for _, _, level in run_levels():
            near, wrong, wild = (cost(level, s) for s in (puzzles.NEAR, puzzles.WRONG, puzzles.WILD))
            self.assertTrue(1 <= near < wrong < wild, level)

    def test_hunt(self):
        seen = set()
        for seed in range(300):
            p = REGISTRY["HUNT"].generate(seed, source("RAW"), level_for(seed))
            n, taken = len(p.pattern), {s + j for s in p.solution for j in range(len(p.pattern))}
            beside = next((i for s in p.solution for i in (s - 1, s + n) if 0 <= i < len(p.data) and i not in taken), None)
            if beside is not None:
                self.assertEqual(p.judge(beside), puzzles.NEAR, seed)       # one cell off an occurrence
            for i in range(len(p.data)):
                if i in taken:
                    continue
                verdict = p.judge(i)
                seen.add(verdict)
                if verdict == puzzles.WILD:
                    self.assertNotIn(p.data[i], p.pattern)                  # a byte the pattern does not contain
            wild = next(i for i in range(len(p.data)) if i not in taken and p.judge(i) == puzzles.WILD)
            self.assertEqual((p.click(wild), p.severity), ("mistake", puzzles.WILD))
        self.assertEqual(seen, {puzzles.NEAR, puzzles.WRONG, puzzles.WILD})

    def test_carve(self):
        for seed in range(200):
            p = REGISTRY["CARVE"].generate(seed, source("RAW"), level_for(seed))
            pos, name = p.files[0]
            magic = puzzles.SIGNATURES[name][0]
            self.assertEqual((p.click(pos + len(magic)), p.severity), ("mistake", puzzles.NEAR))    # the file's body
            for lo, hi in p.decoys:
                self.assertEqual((p.click(lo), p.severity), ("mistake", puzzles.WRONG))             # fell for a decoy
            firsts = {puzzles.SIGNATURES[n][0][0] for n in p.pool}
            clear = [i for i in range(len(p.data)) if not any(q <= i < q + 24 for q, _ in p.files)
                     and not any(lo <= i < hi for lo, hi in p.decoys)]
            for i in clear[:40]:
                want = puzzles.WRONG if p.data[i] in firsts else puzzles.WILD
                self.assertEqual((p.click(i), p.severity), ("mistake", want), (seed, i))
            p.click(pos)
            wrong = next(k for k, n in enumerate(p.options[0]) if n != name)
            self.assertEqual((p.key(str(wrong + 1)), p.severity), ("mistake", puzzles.WRONG))       # misidentified

    def test_payload(self):
        p = REGISTRY["PAYLOAD"].generate(3, source("RAW"), at(3, 4))        # sequences of 3, 4 and 5
        a, b, c = p.targets
        self.assertEqual((len(a), len(b), len(c)), (3, 4, 5))
        self.assertEqual((a[-1], b[-1]), (b[0], c[0]))                     # they chain
        other = next(v for v in range(256) if v not in a + b + c)

        def judge(buffer):
            p.picks = []
            p._buffer = lambda picks: list(buffer)
            return p.judge()

        self.assertEqual(judge(list(b[:3]) + [other] * 3), puzzles.NEAR)   # a byte short of one
        self.assertEqual(judge([other] + list(b[:2]) + [other]), puzzles.WRONG)     # half of one
        self.assertEqual(judge([other] * 6), puzzles.WILD)                 # nothing of any
        # and a real overflow reports what it judged
        p = REGISTRY["PAYLOAD"].generate(5, source("RAW"), 2)
        results = []
        while "mistake" not in results:
            results.append(p.click(p.allowed()[-1]))
            if p.solved:
                p = REGISTRY["PAYLOAD"].generate(p.seed + 1, source("RAW"), 2)
                results = []
        self.assertIn(p.severity, (puzzles.NEAR, puzzles.WRONG, puzzles.WILD))

    def test_payload_ranks(self):
        p = REGISTRY["PAYLOAD"].generate(3, source("RAW"), 2)
        self.assertEqual([name for name, _ in p.ranks()], ["SHALLOW BREACH", "BREACH", "DEEP BREACH"])
        self.assertEqual(p.key("enter"), None)                              # nothing in the buffer yet
        self.assertFalse(p.solved)
        # the known route spells all three: the deepest rank
        apply_actions(p, p.solution_actions())
        self.assertEqual((p.solved, p.rank), (True, ("DEEP BREACH", 2.0)))
        # stop as soon as the shortest is in: a shallow breach, paying half
        p = REGISTRY["PAYLOAD"].generate(3, source("RAW"), 2)
        for i in p.solution:
            p.click(i)
            if p.done()[0]:
                break
        self.assertEqual(p.reached(), 0)
        self.assertEqual(p.key("enter"), "solved")
        self.assertEqual(p.rank, ("SHALLOW BREACH", 0.5))
        self.assertTrue(any(line[0].startswith("  [x]") for line in p.panel()))
        # a full buffer with a sequence in it ends the breach at that rank, not as a mistake
        p = REGISTRY["PAYLOAD"].generate(3, source("RAW"), 2)
        for i in p.solution:
            p.click(i)
            if p.done()[0]:
                break
        while not p.solved:
            self.assertEqual(p.click(p.allowed()[-1]) in ("ok", "solved"), True)
        self.assertGreaterEqual(p.reached(), 0)
        self.assertEqual(p.mistakes, 0)

    def test_xor(self):
        p = next(q for seed in range(40) for q in [REGISTRY["XOR"].generate(seed, source("PROTOCOL"), 5, solved=3)]
                 if q.keylen == 4)                                         # 4-byte key
        key = list(p.solution)
        self.assertEqual(len(key), 4)
        flip = lambda bits, n=4: [k ^ bits for k in key[:n]] + key[n:]
        self.assertEqual(p.judge(flip(0x01, 1)), puzzles.NEAR)             # one bit out
        self.assertEqual(p.judge(flip(0xFF, 2)), puzzles.NEAR)             # half the bytes right
        self.assertEqual(p.judge(flip(0x07, 3)), puzzles.WRONG)            # one byte right, the rest some way off
        self.assertEqual(p.judge(flip(0x01)), puzzles.WRONG)               # every byte wrong, each by a bit
        self.assertEqual(p.judge(flip(0xFF)), puzzles.WILD)                # nothing right at all
        apply_actions(p, [("type", p.typing(flip(0xFF)))])
        self.assertEqual((p.key("enter"), p.severity), ("mistake", puzzles.WILD))
        p = REGISTRY["XOR"].generate(1, source("RAW"), 2)                  # 1-byte key
        k = p.solution[0]
        self.assertEqual([p.judge([k ^ b]) for b in (0x01, 0x03, 0x07, 0x0F, 0xFF)],
                         [puzzles.NEAR, puzzles.NEAR, puzzles.WRONG, puzzles.WILD, puzzles.WILD])

    def test_dissect(self):
        seen = set()
        for seed in range(200):
            p = REGISTRY["DISSECT"].generate(seed, source("PROTOCOL"), level_for(seed))
            f = p.current()
            lo, hi = f.start, f.end - 1
            self.assertEqual((p.select(lo, hi + 1), p.severity), ("mistake", puzzles.NEAR))     # one byte too many
            if hi > lo:
                self.assertEqual((p.select(lo, hi - 1), p.severity), ("mistake", puzzles.NEAR))  # right place, short
            span = p.packet.layer_range(f.layer)
            for other in p.packet.fields.values():
                if other.end <= f.start or other.start >= f.end:
                    same = span[0] <= other.start < span[1]
                    want = puzzles.WRONG if same else puzzles.WILD      # another field: in the same header, or not
                    self.assertEqual((p.select(other.start, other.end - 1), p.severity), ("mistake", want), seed)
                    seen.add(want)
        self.assertEqual(seen, {puzzles.WRONG, puzzles.WILD})

    def test_checksum(self):
        seen = set()
        for seed in range(300):
            p = REGISTRY["CHECKSUM"].generate(seed, source("PROTOCOL"), level_for(seed))
            off, good = p.solution
            bad = p.data[off]
            if abs(bad - good) >= 2:                            # halfway back to the right value: closer, not there
                mid = (bad + good) // 2
                if not p.validate((off, mid)):
                    self.assertEqual(p.judge(off, mid), puzzles.NEAR, seed)
                    seen.add(puzzles.NEAR)
            further = bad + (1 if bad > good else -1)           # one more step the wrong way
            if 0 <= further <= 255 and not p.validate((off, further)):
                self.assertEqual(p.judge(off, further), puzzles.WRONG, seed)
                seen.add(puzzles.WRONG)
            if p.target == "IPv4":                              # the IPv4 checksum does not cover what follows the header
                outside = p.ip_end + 2
                self.assertIsNone(p.click(outside))
                value = "%02x" % (p.data[outside] ^ 0x55)
                self.assertEqual((apply_actions(p, [("type", value)])[-1], p.severity), ("mistake", puzzles.WILD))
                seen.add(puzzles.WILD)
        self.assertEqual(seen, {puzzles.NEAR, puzzles.WRONG, puzzles.WILD})


class GradientTest(unittest.TestCase):
    """Difficulty starts low and rises with every hop, not once per subnet."""

    def test_level_helpers(self):
        self.assertEqual(at(1, 1), 1.0)
        self.assertEqual(at(1, HOPS + 1), at(2, 1))             # an IDS is as deep as the next subnet's entry
        self.assertEqual(LAST, runmod.SUBNETS + 1)
        table = [10, 20, 40]
        self.assertEqual([ramp(x, table) for x in (0, 1, 1.5, 2, 2.25, 3, 9)], [10, 10, 15, 20, 25, 40, 40])
        table = [(1, "a"), (2.5, "b"), (4, "c")]
        self.assertEqual([step(x, table) for x in (0, 1, 2.49, 2.5, 3.9, 4, 9)], list("aaabbcc"))

    def test_tables_are_well_formed(self):
        for cls in list(REGISTRY.values()) + [puzzles.ids, AlertLog, runmod]:
            for name, table in vars(cls).items():
                if not (name.isupper() and isinstance(table, list) and table):
                    continue
                where = "%s.%s" % (getattr(cls, "kind", cls.__name__), name)
                if isinstance(table[0], tuple):                 # a step table
                    starts = [start for start, _ in table]
                    self.assertEqual(starts, sorted(set(starts)), where)
                    self.assertEqual(starts[0], 1, where)       # says what happens from the first node
                    self.assertLessEqual(starts[-1], LAST, where)
                elif name != "MODES":                           # a ramp: one entry per subnet, plus the final IDS
                    self.assertEqual(len(table), runmod.SUBNETS + 1, where)
                    self.assertIn(table, (sorted(table), sorted(table, reverse=True)), where)
                    self.assertNotEqual(table[0], table[-1], where)

    def settings(self, level):
        """Every number that should only ever get harder, as 'bigger is harder'."""
        r = REGISTRY
        out = {"mistake": runmod.RunState.mistake_cost(level), "timeout": runmod.RunState.timeout_cost(level),
               "ids timeout": runmod.RunState.timeout_cost(level, ids=True),
               "ids mods": step(level, puzzles.ids.MOD_COUNT), "ids time": -ramp(level, AlertLog.TIME),
               "ids targets": step(level, AlertLog.TARGETS), "ids decoys": step(level, AlertLog.DECOYS),
               "ids entries": ramp(level, AlertLog.ENTRIES),
               "hunt count": step(level, r["HUNT"].COUNT), "hunt length": -step(level, r["HUNT"].LENGTH),
               "carve files": step(level, r["CARVE"].FILES), "carve decoys": step(level, r["CARVE"].DECOYS),
               "payload size": step(level, r["PAYLOAD"].SIZE), "payload slack": -step(level, r["PAYLOAD"].SLACK),
               "payload targets": sum(step(level, r["PAYLOAD"].TARGETS)),
               "xor usual": step(level, r["XOR"].USUAL), "dissect rounds": step(level, r["DISSECT"].ROUNDS),
               "reassemble segments": step(level, r["REASSEMBLE"].SEGMENTS),
               "reassemble seq": step(level, r["REASSEMBLE"].SEQ)[0] - step(level, r["REASSEMBLE"].SEQ)[1],
               "reassemble decoys": step(level, r["REASSEMBLE"].DECOYS)}
        for kind, cls in r.items():
            out[kind + " time"] = -ramp(level, cls.TIME)
        for kind in ("HUNT", "CARVE", "XOR"):
            out[kind + " size"] = ramp(level, r[kind].SIZE)
        return out

    def test_every_hop_is_at_least_as_hard_as_the_one_before(self):
        steps = [self.settings(level) for _, _, level in run_levels()]
        for a, b in zip(steps, steps[1:]):
            for name in a:
                self.assertLessEqual(a[name], b[name], name)
        for name in steps[0]:
            self.assertLess(steps[0][name], steps[-1][name], name)

    def test_it_rises_inside_a_subnet_not_only_between_them(self):
        for subnet in range(1, runmod.SUBNETS + 1):
            a, b = self.settings(at(subnet, 1)), self.settings(at(subnet, HOPS))
            harder = [name for name in a if b[name] > a[name]]
            self.assertGreaterEqual(len(harder), 8, (subnet, harder))
        # and the generated puzzles follow the tables: timers shrink hop by hop
        for kind, cls in REGISTRY.items():
            mode = "PROTOCOL" if "RAW" not in cls.modes else "RAW"
            # some kinds vary their timer a little node to node, so follow the average over a few seeds
            times = [sum(cls.generate(seed, source(mode), level).time_limit for seed in range(12)) / 12
                     for _, _, level in run_levels()]
            half = len(times) // 2
            self.assertGreater(sum(times[:half]) / half, sum(times[half:]) / (len(times) - half), kind)
            self.assertGreater(times[0], times[-1], kind)
            self.assertGreaterEqual(len(set(times)), 15, kind)

    def test_the_first_node_is_gentle(self):
        for seed in range(100):
            p = REGISTRY["HUNT"].generate(seed, source("RAW"), 1)
            self.assertEqual(len(p.pattern), 4)
            self.assertIn(len(p.solution), (2, 3))
            self.assertLessEqual(len(p.lookalikes), 2)
            self.assertLessEqual(len(p.data), 136)
            p = REGISTRY["CARVE"].generate(seed, source("RAW"), 1)
            self.assertEqual((len(p.files), len(p.decoys)), (1, 0))
            self.assertLessEqual(len(p.data), 96)
            p = REGISTRY["DISSECT"].generate(seed, source("PROTOCOL"), 1)
            self.assertEqual(len(p.fields), 2)
            for f in p.fields:                                  # the panel says where each field is
                self.assertIn("+0x%02X" % (f.start - p.packet.layer_range(f.layer)[0]), p.help_for(f)[-1])
        first, last = self.settings(1), self.settings(LAST)
        self.assertLessEqual(first["mistake"], 2)
        self.assertGreaterEqual(-first["HUNT time"], 1.5 * -last["HUNT time"])

    def test_kinds_come_in_one_at_a_time(self):
        self.assertEqual(kinds_for_mode("RAW", 1), ["HUNT", "CARVE"])
        self.assertEqual(kinds_for_mode("PROTOCOL", 1), ["HUNT", "DISSECT", "CARVE"])
        for mode in ("RAW", "PROTOCOL", "LIVE"):
            seen = []
            for _, _, level in run_levels():
                kinds = kinds_for_mode(mode, level)
                self.assertEqual(kinds[:len(seen)], seen)       # nothing is ever taken away
                self.assertLessEqual(len(kinds) - len(seen), 3 if not seen else 1, (mode, level))
                seen = kinds
            self.assertEqual(seen, kinds_for_mode(mode))
            self.assertEqual(kinds_for_mode(mode, at(3)), kinds_for_mode(mode))     # all in by subnet 3

    def test_maps_only_hold_kinds_that_are_in_play(self):
        for mode in ("RAW", "PROTOCOL"):
            met = set()
            for seed in range(300):
                subnet = 1 + seed % 3
                net = runmod.generate_subnet(random.Random(seed), subnet, source(mode))
                for node in net.nodes.values():
                    if node.kind in REGISTRY:
                        self.assertLessEqual(REGISTRY[node.kind].first, at(subnet, node.layer + 1), (seed, node))
                        met.add(node.kind)
                if subnet == 1:
                    self.assertNotIn("XOR", {n.kind for n in net.nodes.values()})
                    self.assertTrue({n.kind for n in net.layer(0)} <= {"HUNT", "CARVE", "DISSECT"})
            self.assertEqual(met, set(kinds_for_mode(mode)))    # and every kind does turn up

    def test_ids_modifiers_start_mild(self):
        self.assertEqual(set(puzzles.ids.MOD_FROM), set(puzzles.ids.MODIFIERS))
        drawn = {}
        for subnet in range(1, runmod.SUBNETS + 1):
            for seed in range(200):
                p = puzzles.ids.generate(seed, source("RAW"), at(subnet, HOPS + 1))
                drawn.setdefault(subnet, set()).update(p.modifiers)
        self.assertEqual(drawn[1], {"THROTTLE", "BLACKOUT", "BLIND"})
        self.assertEqual(drawn[2], drawn[1] | {"LOSS"})
        for subnet in (3, 4, 5):
            self.assertEqual(drawn[subnet], set(puzzles.ids.MODIFIERS))

    def test_dissect_help_fades_layer_by_layer(self):
        def helps(level, layer):
            for seed in range(200):
                p = REGISTRY["DISSECT"].generate(seed, source("PROTOCOL"), level)
                for f in p.fields:
                    if f.layer == layer:
                        return p.help_for(f)
            self.fail("no %s field at level %s" % (layer, level))

        self.assertIn("field is at +0x", helps(at(1), "IPv4")[1])           # new: offset and size
        self.assertIn("IPv4 header starts at 0x000E", helps(at(1, 6), "IPv4")[0])
        self.assertIn("long", helps(at(2), "IPv4")[1])                      # a subnet on: size only
        self.assertEqual(helps(at(3), "IPv4"), [])                          # then nothing
        self.assertIn("field is at +0x", helps(at(2), "TCP")[1])            # but TCP is new in subnet 2
        self.assertIn("long", helps(at(3, 4), "TCP")[1])
        self.assertEqual(helps(at(4), "TCP"), [])
        self.assertIn("DNS message starts at", helps(at(3), "DNS")[0])


class MapTest(unittest.TestCase):
    def test_subnets_are_well_formed(self):
        for mode in ("RAW", "PROTOCOL", "LIVE"):
            src = source(mode)
            allowed = set(kinds_for_mode(mode)) | {"FOOTHOLD", "IDS"}
            for seed in range(300):
                net = runmod.generate_subnet(random.Random(seed), 1 + seed % 5, src)
                nodes = net.nodes
                self.assertTrue({n.kind for n in nodes.values()} <= allowed, (mode, seed))
                starts = net.layer(0)
                self.assertGreaterEqual(len(starts), 2)
                self.assertTrue(all(n.kind in REGISTRY for n in starts))
                # every node is reachable from an entry node, and every node leads to the boss
                reach, todo = set(), [n.id for n in starts]
                while todo:
                    i = todo.pop()
                    if i not in reach:
                        reach.add(i)
                        todo += nodes[i].next
                self.assertEqual(reach, set(nodes))
                for n in nodes.values():
                    if n is not net.boss:
                        self.assertTrue(n.next, (mode, seed, n))
                        self.assertTrue(all(nodes[i].layer == n.layer + 1 for i in n.next))
                self.assertEqual(net.boss.kind, "IDS")
                self.assertTrue(any(n.kind == "FOOTHOLD" for n in net.layer(runmod.LAYERS - 1)))

    def test_run_state_progression(self):
        state = runmod.RunState("RAW", source("RAW"), 42)
        self.assertEqual(state.available(), state.subnet.layer(0))
        for level in range(1, runmod.SUBNETS + 1):
            self.assertEqual(state.level, level)
            hops = 0
            while state.available():
                node = state.available()[0]
                state.move_to(node)
                state.complete(node)
                hops += 1
                if node.kind == "IDS":
                    break
            self.assertEqual(hops, runmod.LAYERS + 1)
        self.assertEqual(state.over, "won")
        self.assertEqual(state.available(), [])

    def test_trace_ends_the_run_at_100(self):
        state = runmod.RunState("RAW", source("RAW"), 1)
        state.add_trace(99.5)
        self.assertIsNone(state.over)
        state.add_trace(-200)
        self.assertEqual(state.trace, 0)
        state.add_trace(100)
        self.assertEqual(state.over, "traced")
        self.assertEqual(state.available(), [])


if __name__ == "__main__":
    unittest.main()
