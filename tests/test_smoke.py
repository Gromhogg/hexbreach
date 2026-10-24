"""Headless smoke test: the whole game loop, driven by scripted mouse and
keyboard events, from the title screen through a complete run and back."""
import json
import math
import os
import random
import sys
import tempfile
import time
import unittest

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

import autoplay  # noqa: E402
import glossary  # noqa: E402
import tools  # noqa: E402
import hexview  # noqa: E402
import main  # noqa: E402
import puzzles  # noqa: E402
import run as runmod  # noqa: E402
import scenes  # noqa: E402
import sources  # noqa: E402
import ui  # noqa: E402

ALL_SCENES = {"TitleScene", "ModeScene", "ToolkitScene", "MapScene", "PuzzleScene", "GameOverScene"}
MASHED_SCENES = ALL_SCENES | {"TutorialScene"}


class SmokeTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="hexbreach-smoke-")
        self.save_path = os.path.join(self.dir, "save.json")
        self.captures = os.path.join(self.dir, "captures")
        os.mkdir(self.captures)

    def play(self, mode, seed, **bot_args):
        game = main.Game(save_path=self.save_path, captures_dir=self.captures, seed=seed)
        bot = autoplay.Bot(game, mode=mode, seed=seed, **bot_args)
        game.loop(bot=bot, max_frames=60000, fixed_dt=0.05)
        self.assertTrue(bot.finished, "run did not finish: stuck in %s" % type(game.scene).__name__)
        return game, bot

    def saved(self):
        with open(self.save_path) as fh:
            return json.load(fh)

    def test_full_run_in_every_mode(self):
        rng, syn, frames = random.Random(1), sources.SynthSource(), []
        for i in range(40):
            frames += syn.flow(rng, 1 + i % 5)
        sources.write_pcapng(os.path.join(self.captures, "mine.pcapng"), frames)
        endpoints = set()
        for f in frames:
            i = sources.parse(f).info
            endpoints |= {"%s:%d" % (i["src_ip"], i["sport"]), "%s:%d" % (i["dst_ip"], i["dport"])}

        for n, mode in enumerate(("RAW", "PROTOCOL", "LIVE")):
            game, bot = self.play(mode, seed=100 + n, pace=2)
            state = game.run_state
            self.assertEqual(bot.outcome, "won", mode)
            self.assertEqual(state.stats["ids"], runmod.SUBNETS)
            self.assertEqual(state.stats["nodes"], runmod.SUBNETS * (runmod.LAYERS + 1))
            self.assertEqual(state.stats["mistakes"], 0)
            self.assertTrue(ALL_SCENES <= bot.seen, bot.seen)
            want = {"PAYLOAD", "HUNT", "XOR", "CARVE", "REASSEMBLE", "IDS"} | (set() if mode == "RAW" else {"DISSECT", "CHECKSUM"})
            self.assertEqual(bot.kinds, want, mode)
            self.assertIsInstance(game.scene, scenes.TitleScene)
            if mode == "LIVE":
                self.assertFalse(state.source.using_fallback)
                names = {node.name for node in state.subnet.nodes.values()}
                self.assertTrue(names <= endpoints)         # map nodes named after the capture

        data = self.saved()
        self.assertEqual((data["runs"], data["wins"]), (3, 3))
        self.assertEqual(data["deepest_subnet"], runmod.SUBNETS)
        self.assertEqual(data["ids_evaded"], 3 * runmod.SUBNETS)
        self.assertEqual(set(data["unlocked"]), set(tools.TOOLS))   # 15 IDS kills unlock everything
        self.assertEqual(set(data["best_run"]), {"RAW", "PROTOCOL", "LIVE"})
        self.assertIn("ip.checksum", data["manual"])
        self.assertTrue(data["signatures"])
        self.assertTrue(set(data["best_solve"]) >= {"PAYLOAD", "HUNT", "XOR", "CARVE", "DISSECT", "CHECKSUM",
                                                   "REASSEMBLE"})

    def test_mistakes_add_trace_but_a_careful_run_survives(self):
        game, bot = self.play("PROTOCOL", seed=7, pace=2, wrong=0.5)
        state = game.run_state
        self.assertGreater(state.stats["mistakes"], 3)
        self.assertIn(bot.outcome, ("won", "traced"))
        self.assertEqual(self.saved()["runs"], 1)

    def test_doing_nothing_gets_you_traced(self):
        game, bot = self.play("RAW", seed=3, pace=2, solve=False)
        state = game.run_state
        self.assertEqual(bot.outcome, "traced")
        self.assertEqual(state.trace, 100)
        self.assertEqual(state.stats["solved"], 0)
        self.assertEqual(state.stats["failed"], 0)              # it never jacked out: overtime ran the trace up
        data = self.saved()
        self.assertEqual((data["runs"], data["wins"], data["deepest_subnet"]), (1, 0, 1))
        self.assertEqual(data["best_run"], {})

    def test_the_clock_raises_trace_everywhere_and_faster_near_the_ids(self):
        state = runmod.RunState("RAW", sources.RandomSource(), 11)
        self.assertEqual(state.clock_tick(), runmod.CLOCK_TICK)
        for _ in range(20 * 60):
            state.tick(1 / 60)
        self.assertEqual(state.trace, runmod.CLOCK_TRACE)          # 20 seconds on the map: 1%
        state.move_to(state.subnet.boss)
        self.assertEqual(state.clock_tick(), runmod.CLOCK_TICK_IDS)
        state.trace, state.clock = 0.0, 0.0
        for _ in range(20 * 60):
            state.tick(1 / 60)
        self.assertEqual(state.trace, 2 * runmod.CLOCK_TRACE)      # the same time at the IDS: 2%
        # it keeps going inside a node, briefing and all
        game = main.Game(save_path=self.save_path, captures_dir=self.captures, seed=1)
        scene = game.practice("HUNT", "RAW", 1)
        before = scene.run.trace
        for _ in range(20 * 60):
            game.frame(1 / 60)
        self.assertGreater(scene.run.trace, before)

    def test_live_with_no_captures_falls_back(self):
        game, bot = self.play("LIVE", seed=5, pace=2)
        self.assertEqual(bot.outcome, "won")
        self.assertTrue(game.run_state.source.using_fallback)

    def test_the_title_dump_is_live_and_read_only(self):
        rows = scenes.TITLE_ROWS
        self.assertTrue(all(len(row) == 16 for row in rows))    # no word is split across rows
        self.assertEqual(b" ".join(rows).split(), b"a hex-dump netrunning roguelike.".split())
        game = main.Game(save_path=self.save_path, captures_dir=self.captures, seed=1)
        title, bot = game.scene, autoplay.Bot(game)
        dump = title.dump
        title.typing = None
        self.assertEqual(bytes(dump.data), b"".join(rows))
        self.assertEqual(dump.chosen, (2, 9))                   # "hex-dump" selected to begin with
        self.assertEqual(bytes(dump.data[2:10]), b"hex-dump")
        self.assertGreater(dump.byte_rect(0, "ascii").x, dump.byte_rect(15).right)     # the text is the right-hand pane
        # the name is not in the dump: it is set large in the top left, above it
        game.frame(0.02)
        name = [(x, y, size) for x, y, s, size in ui.runs if s == "HEXBREACH"]
        self.assertEqual(name, [(title.X, title.Y_TITLE, scenes.TITLE_SIZE)])
        self.assertGreater(scenes.TITLE_SIZE, 2 * dump.size)
        self.assertLessEqual(title.Y_TITLE + ui.lh(scenes.TITLE_SIZE), dump.y)
        self.assertTrue(all(y >= title.Y_TITLE for x, y, s, _ in ui.runs if s != ui.runs[0][2]))   # only the path is above

        def colour(i, pane="hex"):
            game.frame(0.02)
            pos = dump.byte_rect(i, pane).topleft
            return game.screen.get_at((ui.X(pos[0]), ui.Y(pos[1])))[:3]

        self.assertEqual((colour(3), colour(3, "ascii"), colour(20), colour(20, "ascii")),
                         (ui.TAN, ui.TAN, ui.BLACK, ui.BLACK))
        # pointing at a byte puts the cursor on its letter as well, and the other way round
        bot.move(dump.byte_rect(20).center)
        self.assertEqual((colour(20), colour(20, "ascii"), dump.hover), (ui.TAN, ui.TAN, 20))
        bot.move(dump.byte_rect(40, "ascii").center)
        self.assertEqual((colour(40), colour(40, "ascii"), colour(20), dump.hover), (ui.TAN, ui.TAN, ui.BLACK, 40))
        dump._moved -= ui.BLINK * 1.5                           # it blinks
        self.assertEqual((colour(40), colour(40, "ascii")), (ui.BLACK, ui.BLACK))
        # dragging, in either pane, moves the selection
        for a, b, pane in ((18, 25, "hex"), (32, 41, "ascii")):
            start, end = dump.byte_rect(a, pane).center, dump.byte_rect(b, pane).center
            bot.move(start)
            bot.down(start)
            bot.move(end)
            bot.up(end)
            bot.move((5, 5))
            self.assertEqual((colour(a), colour(b, "ascii"), colour(3)), (ui.TAN, ui.TAN, ui.BLACK))
            self.assertEqual(dump.chosen, (a, b))
        # and nothing typed or clicked changes a byte
        for ch in "abcdef":
            bot.char(ch)
        bot.click(dump.byte_rect(5).center)
        game.frame(0.02)
        self.assertEqual(bytes(dump.data), b"".join(rows))
        self.assertIs(game.scene, title)

    def test_a_click_as_the_map_opens_is_safe(self):
        game = main.Game(save_path=self.save_path, captures_dir=self.captures, seed=1)
        bot = autoplay.Bot(game)
        for ch in "121":                                        # new run, RAW, first tool: all in one frame
            bot.char(ch)
        bot.click((60, 130))                                    # and a click before the map has drawn
        game.frame(0.02)
        self.assertIsInstance(game.scene, (scenes.MapScene, scenes.PuzzleScene))

    def test_fullscreen_from_the_menu_and_the_keyboard(self):
        game = main.Game(save_path=self.save_path, captures_dir=self.captures, seed=1)
        bot, title, windowed = autoplay.Bot(game), game.scene, game.screen.get_size()
        self.assertFalse(game.fullscreen)
        self.assertEqual((ui.SCALE, ui.to_layout((640, 400))), (1.0, (640, 400)))
        self.assertEqual([it["label"] for it in title.menu.items], ["NEW RUN", "TUTORIAL", "LOGS", "MENU"])
        bot.char("4")                                               # MENU answers to M, not to its number
        game.frame(0.05)
        self.assertIs(game.scene, title)
        bot.click(title.menu.item_rect(3).center)                   # the switch lives in the M menu
        game.frame(0.05)
        menu = game.scene
        self.assertIsInstance(menu, scenes.MenuScene)
        item = next(i for i, it in enumerate(menu.menu.items) if it["label"] == "FULLSCREEN: OFF")
        bot.click(menu.menu.item_rect(item).center)
        game.frame(0.05)
        game.frame(0.05)
        self.assertTrue(game.fullscreen)
        self.assertTrue(self.saved()["fullscreen"])
        self.assertIs(game.scene, menu)                             # the menu stays open
        self.assertEqual(menu.menu.items[item]["label"], "FULLSCREEN: ON")
        self.assertEqual(menu.menu.index, item)                     # the cursor stays on it
        # the layout now fills the new surface, corner to corner, and the mouse still lands where it points
        size = game.screen.get_size()
        self.assertNotEqual(size, windowed)
        self.assertEqual(ui.SCALE, min(size[0] / ui.BASE_W, size[1] / ui.BASE_H))
        for edge, pixels in zip(ui.box((0, 0, ui.W, ui.H))[2:], size):
            self.assertTrue(pixels - ui.SCALE - 1 < edge <= pixels, (edge, pixels))     # to within a unit
        bot.click(menu.menu.item_rect(item).center)
        game.frame(0.05)
        self.assertFalse(game.fullscreen)
        self.assertEqual(menu.menu.items[item]["label"], "FULLSCREEN: OFF")
        bot.key(pygame.K_ESCAPE)
        game.frame(0.05)
        self.assertIs(game.scene, title)

        # the keys work in any scene and are not passed on to it
        bot.char("2")
        game.frame(0.05)
        scene = game.scene
        self.assertIsInstance(scene, scenes.TutorialScene)
        for key, mod in ((pygame.K_F11, 0), (pygame.K_f, pygame.KMOD_META), (pygame.K_RETURN, pygame.KMOD_ALT)):
            before = game.fullscreen
            pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=key, unicode="", mod=mod, scancode=0))
            game.frame(0.05)
            self.assertEqual(game.fullscreen, not before)
            self.assertIs(game.scene, scene)
            self.assertEqual((scene.i, scene.misses, scene.typed), (0, 0, ""))
        self.assertTrue(game.fullscreen)

        # it is remembered, and the command line can overrule it without changing the save
        self.assertTrue(main.Game(save_path=self.save_path, captures_dir=self.captures).fullscreen)
        self.assertFalse(main.Game(save_path=self.save_path, captures_dir=self.captures, fullscreen=False).fullscreen)
        self.assertTrue(self.saved()["fullscreen"])

    def test_tutorial_from_the_title_screen(self):
        game = main.Game(save_path=self.save_path, captures_dir=self.captures, seed=1)
        title = game.scene
        self.assertEqual(title.menu.items[title.menu.index]["label"], "TUTORIAL")  # offered first on a new save
        bot = autoplay.Bot(game)
        bot.key(pygame.K_RETURN)
        game.frame(0.05)
        scene = game.scene
        self.assertIsInstance(scene, scenes.TutorialScene)
        self.assertEqual([s["want"][0] if s["want"] else None for s in scene.steps],
                         ["click", "click", "select", "type", None])

        # wrong answers cost nothing; the second one lights up the answer
        target = scene.want[1]
        for n in (1, 2):
            bot.click(scene.hex.byte_rect(target + n).center)
            game.frame(0.05)
            self.assertEqual((scene.i, scene.solved, scene.misses), (0, False, n))
        self.assertIn("0x%04X" % (target + 2), scene.note[0])
        self.assertEqual(scene.hex.styles, {target: "flash"})

        seen = []
        for _ in range(400):
            if game.scene is not scene:
                break
            if scene.i not in seen:
                seen.append(scene.i)
            bot.on_TutorialScene(scene)
            game.frame(0.2)
        self.assertEqual(seen, [0, 1, 2, 3, 4])
        self.assertIs(game.scene, title)
        self.assertTrue(self.saved()["tutorial"])
        self.assertEqual(title.menu.items[title.menu.index]["label"], "NEW RUN")   # and not pushed again
        self.assertEqual(self.saved()["runs"], 0)

    def test_leaving_the_tutorial_early(self):
        game = main.Game(save_path=self.save_path, captures_dir=self.captures, seed=1)
        bot = autoplay.Bot(game)
        bot.char("2")
        game.frame(0.05)
        self.assertIsInstance(game.scene, scenes.TutorialScene)
        bot.key(pygame.K_ESCAPE)
        game.frame(0.05)
        self.assertIsInstance(game.scene, scenes.TitleScene)
        self.assertFalse(game.save.data["tutorial"])

    def test_a_run_gets_harder_hop_by_hop(self):
        """The level a puzzle scene is built at follows the node's place on the map."""
        game = main.Game(save_path=self.save_path, captures_dir=self.captures, seed=11)
        state = runmod.RunState("PROTOCOL", sources.SynthSource(), 11)
        game.run_state = state
        game.push(scenes.MapScene(game, state))
        seen = []
        while not state.over:
            node = state.available()[0]
            game.scene.enter(node)
            scene = game.scene
            if isinstance(scene, scenes.PuzzleScene):
                self.assertEqual(scene.level, puzzles.at(state.level, node.layer + 1))
                seen.append((scene.level, scene.mistake_cost, scene.timeout_cost, scene.is_boss))
            game.pop()
            state.complete(node)
        levels = [s[0] for s in seen]
        self.assertEqual(levels, sorted(levels))
        self.assertEqual((levels[0], levels[-1]), (1.0, runmod.SUBNETS + 1))
        self.assertGreater(len(set(levels)), 3 * runmod.SUBNETS)
        self.assertEqual([s[1] for s in seen], sorted(s[1] for s in seen))
        self.assertLess(seen[0][1], seen[-1][1])
        self.assertLess(seen[0][2], seen[-1][2])

    def test_the_map_lights_the_path_taken(self):
        game = main.Game(save_path=self.save_path, captures_dir=self.captures, seed=11)
        state = runmod.RunState("RAW", sources.RandomSource(), 11)
        game.run_state = state
        game.push(scenes.MapScene(game, state))
        scene = game.scene
        self.assertEqual(state.path(), [])
        taken = []
        for _ in range(3):
            node = state.available()[-1]
            state.move_to(node)
            state.complete(node)
            taken.append(node)
        self.assertEqual(state.path(), taken)
        for _ in range(60):
            game.frame(0.02)
        cw, lh = ui.cw(scenes.MAP_SIZE), ui.lh(scenes.MAP_SIZE)

        def line(node):
            """The colours of the line where it leaves a node."""
            x = scene.X + (node.layer * scenes.COL_W + scenes.NAME_W) * cw
            y = scene.Y + (node.slot * scenes.SLOT_H + 1) * lh
            left, top, wide, high = ui.box((x, y, cw, lh))
            return {tuple(game.screen.get_at((left + i, top + j)))[:3]
                    for i in range(wide) for j in range(high)} - {ui.BLACK}

        for node in taken[:-1]:
            self.assertEqual(line(node), {ui.GREEN}, node)          # the way in so far
        self.assertEqual(line(taken[-1]), {ui.AMBER})               # from where you are: the ways on
        for node in state.subnet.nodes.values():
            if node not in taken and node.next:
                self.assertEqual(line(node), {ui.DIM}, node)        # everything else stays in the background
        # a new subnet starts with no path
        while state.level == 1:
            node = state.available()[0]
            state.move_to(node)
            state.complete(node)
        self.assertEqual(state.path(), [])

    def test_codepage_gives_every_byte_a_symbol(self):
        """CODEPAGE: the ASCII pane shows a symbol for every byte, never a dot,
        so a HUNT fake no longer reads like a copy there."""
        from puzzles.base import CP437, printable
        info = tools.TOOLS["CODEPAGE"]
        self.assertFalse(info.active or info.traceable)
        self.assertIn("CODEPAGE", tools.STARTERS)
        self.assertEqual((len(CP437), len(set(CP437))), (256, 256))             # no two bytes alike
        self.assertEqual(CP437[32:127], "".join(map(chr, range(32, 127))))      # ASCII reads as it always did
        self.assertFalse(any(ch.isspace() or not ch.isprintable() for i, ch in enumerate(CP437) if i != 32))
        self.assertEqual(printable(b"Ss\x14\xc0"), "Ss..")
        self.assertEqual(printable(b"Ss\x14\xc0", codepage=True), "Ss\u00b6\u2514")
        game = main.Game(save_path=self.save_path, captures_dir=self.captures, seed=9)
        scene = game.practice("HUNT", "RAW", 2)
        p, hx = scene.puzzle, scene.hex
        self.assertTrue(p.lookalikes)
        bot = autoplay.Bot(game)
        bot.key(pygame.K_SPACE)
        for _ in range(40):
            game.frame(0.05)

        def pane():
            """The ASCII pane as drawn, byte by byte."""
            game.frame(0.05)
            at = {(hx.byte_rect(i, "ascii").x, hx.byte_rect(i, "ascii").y): i for i in range(len(p.data))}
            return {at[x, y]: s for x, y, s, _ in ui.runs if (x, y) in at}

        def reads(start, shown):
            return "".join(shown[start + j] for j in range(len(p.pattern)))

        fake, copy = p.lookalikes[0][0], p.solution[0]
        shown = pane()
        self.assertEqual(reads(fake, shown), reads(copy, shown))                # the same dots
        self.assertIn(("  ascii: %s" % printable(p.pattern), "dim"), p.panel())
        self.assertTrue(any("same ASCII" in row[0] for row in p.panel()))
        scene.run.install("CODEPAGE")
        shown = pane()
        self.assertEqual(shown, {i: CP437[b] for i, b in enumerate(p.data)})    # every byte, its own symbol
        self.assertNotEqual(reads(fake, shown), reads(copy, shown))             # the fake is told apart
        self.assertIn(("  ascii: %s" % reads(copy, shown), "dim"), p.panel())   # the panel reads as the pane does
        self.assertFalse(any("same ASCII" in row[0] for row in p.panel()))

    def test_tools_in_a_puzzle_scene(self):
        game = main.Game(save_path=self.save_path, captures_dir=self.captures, seed=9)
        scene = game.practice("PAYLOAD", "RAW", 2)
        state = scene.run
        for d in ("BRUTEFORCE", "SNAPSHOT", "PROXY"):
            state.install(d)
        scene.charges = tools.node_charges(state.tools)
        bot = autoplay.Bot(game)
        bot.key(pygame.K_SPACE)
        game.frame(0.05)
        self.assertEqual(scene.phase, "play")
        bot.key(pygame.K_q, "q")                    # slot 1: BRUTEFORCE
        game.frame(0.05)
        self.assertTrue(scene.puzzle.wild_next)
        self.assertEqual(scene.charges["BRUTEFORCE"], 0)
        bot.click(scene.hex.byte_rect(scene.puzzle.allowed()[0]).center)
        game.frame(0.05)
        self.assertEqual(len(scene.puzzle.picks), 1)
        bot.key(pygame.K_w, "w")                    # slot 2: SNAPSHOT
        game.frame(0.05)
        self.assertEqual(scene.puzzle.picks, [])
        bot.key(pygame.K_r, "r")                    # slot 3: PROXY
        game.frame(0.05)
        left = scene.left
        for _ in range(20):
            game.frame(0.05)
        self.assertEqual(scene.left, left)          # timer held while frozen
        self.assertEqual(state.trace, 0)

    def node_scene(self, kind, seed=2):
        """A run on its map, walked to the first node of the given kind and jacked in."""
        game = main.Game(save_path=self.save_path, captures_dir=self.captures, seed=seed)
        state = runmod.RunState("RAW", sources.RandomSource(), seed)
        game.run_state = state
        game.push(scenes.MapScene(game, state))
        while state.available()[0].kind != kind:
            node = state.available()[0]
            state.move_to(node)
            state.complete(node)
        node = state.available()[0]
        bot = autoplay.Bot(game, solve=False, pace=1)
        game.scene.enter(node)
        bot.key(pygame.K_SPACE)
        game.frame(0.05)
        self.assertEqual(game.scene.phase, "play")
        return game, state, node, bot

    def test_xor_gets_harder_each_time_one_is_solved(self):
        """XOR has levels of its own: a run's first XOR is level 1 wherever it
        is met, and each one solved moves the next one up, to 3 or 4. After
        the first three, one may be a double, with levels of its own."""
        game = main.Game(save_path=self.save_path, captures_dir=self.captures, seed=4)
        state = runmod.RunState("RAW", sources.RandomSource(), 4)
        game.run_state = state
        state.level = 4                         # deep in the run: its first XOR is still the easy one
        met, doubles = [], []
        for n in range(6):
            node = runmod.Node(0, n, "XOR", "node-%d" % n, 100 + n)
            scene = scenes.PuzzleScene.open(game, state, node, state.node_level(node))
            met.append(scene.puzzle.xor_level)
            doubles.append(scene.puzzle.double)
            if n == 0:                          # looked at, or left unsolved: the next one is no harder
                scene.jack_in()
                scene.overtime = True
                scene._end("jacked out")
                again = scenes.PuzzleScene.open(game, state, node, state.node_level(node))
                self.assertEqual((state.solved, again.puzzle.xor_level), ({}, 1))
            scene._end("solved")
            self.assertEqual(state.solved, {"XOR": n + 1})
        self.assertEqual(met[:3], [1, 2, 3], met)
        self.assertFalse(any(doubles[:3]), doubles)
        self.assertTrue(all(lv in (3, 4) for lv, double in zip(met[3:], doubles[3:]) if not double), met)
        # practice has no run behind it: it is as hard as XOR usually is by that level
        self.assertEqual([game.practice("XOR", "RAW", level).puzzle.xor_level for level in (2, 2.5, 3)], [1, 2, 3])

    def test_a_payload_breach_pays_by_its_rank(self):
        def breach(stop_at):
            """Play PAYLOAD along its known route, uploading once this many sequences are in."""
            game, state, node, bot = self.node_scene("PAYLOAD")
            scene, p = game.scene, game.scene.puzzle
            for i in p.solution:
                if sum(p.done()) >= stop_at:
                    break
                bot.click(scene.hex.byte_rect(i).center)
                game.frame(0.05)
            if not p.solved:
                bot.key(pygame.K_RETURN)
                game.frame(0.05)
            self.assertEqual((scene.phase, scene.result), ("result", "solved"))
            return p.rank[0], state.credits - runmod.START_CREDITS, scene.banner[0]

        shallow = breach(1)
        deep = breach(3)
        self.assertEqual((shallow[0], deep[0]), ("SHALLOW BREACH", "DEEP BREACH"))
        self.assertLess(shallow[1], deep[1])
        self.assertTrue(shallow[2].startswith("SHALLOW BREACH  +"))
        self.assertTrue(deep[2].startswith("DEEP BREACH  +"))
        # the briefing says what each rank pays
        game, state, node, bot = self.node_scene("PAYLOAD")
        rows = [row for row in game.scene.brief_rows()[2] if row is not None]
        pays = next(text for label, text, _ in rows if label == "PAYS")
        self.assertTrue(all(word in pays for word in ("SHALLOW", "BREACH", "DEEP", "credits")), pays)
        labels = [label for label, _, _ in rows]
        self.assertEqual(labels[:4], ["DO", "1.", "2.", "3."])          # the steps, under what to do
        self.assertEqual(labels[4:7], ["SHALLOW", "BREACH", "DEEP"])

    def overtime(self, game, seconds):
        """Run the clock out, then on into overtime for this long."""
        game.scene.left = 0.01
        for _ in range(round(seconds / 0.05) + 1):
            game.frame(0.05)

    def test_running_out_of_time_is_overtime_and_jacking_out_means_doing_the_node_again(self):
        for kind in ("HUNT", "IDS"):
            game, state, node, bot = self.node_scene(kind)
            first, seed, data = game.scene, node.seed, bytes(game.scene.puzzle.data)
            before = state.came_from
            self.overtime(game, 1.0)
            # still in, the TRACE rising a little every half second
            self.assertEqual((first.phase, first.overtime, first.result), ("play", True, None))
            self.assertAlmostEqual(state.trace, 2 * first.tick_cost())
            self.assertAlmostEqual(first.tick_cost(), tools.trace_cost(
                state.tools, state.timeout_cost(first.level, ids=kind == "IDS") / 8, "timeout"))
            cost = state.trace
            bot.key(pygame.K_ESCAPE)                            # jack out
            game.frame(0.05)
            self.assertEqual(first.result, "jacked out")
            self.assertIn("IDS NOT EVADED" if kind == "IDS" else "NODE NOT BREACHED", first.banner[0])
            self.assertEqual(state.stats["failed"], 1)
            bot.key(pygame.K_SPACE)
            game.frame(0.05)
            # not let through: back on the map, the node not done, and a fresh puzzle next time
            self.assertIsInstance(game.scene, scenes.MapScene)
            self.assertIs(state.position, before)
            self.assertFalse(node.done)
            self.assertIn(node, state.available())
            game.scene.enter(node)
            again = game.scene
            self.assertIsInstance(again, scenes.PuzzleScene)
            self.assertIsNot(again, first)
            self.assertEqual((again.phase, again.level, again.left), ("play", first.level, again.total))
            self.assertNotEqual((node.seed, bytes(again.puzzle.data)), (seed, data))
            self.assertEqual(len(game.stack), 3)                # title, map, node: nothing piled up
            self.assertEqual(state.stats["nodes"], sum(n.done for n in state.subnet.nodes.values()) + 1)
            # and it can then be solved and left the normal way
            bot.solve = True
            for _ in range(600):
                if not isinstance(game.scene, scenes.PuzzleScene):
                    break
                bot.step()
                game.frame(0.02)
            self.assertTrue(node.done)
            self.assertEqual(state.level, 2 if kind == "IDS" else 1)
            self.assertAlmostEqual(state.trace, max(0, cost - (runmod.SUBNET_COOLDOWN if kind == "IDS" else 0)))

    def test_finishing_in_overtime_pays_half(self):
        game, state, node, bot = self.node_scene("HUNT")
        scene = game.scene
        self.overtime(game, 0.6)
        bot.solve = True
        for _ in range(600):
            if scene.phase != "play":
                break
            bot.step()
            game.frame(0.02)
        self.assertEqual(scene.result, "solved")
        self.assertIn("half pay", scene.banner[0])
        base = state.score("HUNT", 0, scene.level, scene.mistakes, scene.factor * 0.5)[0]
        self.assertIn("pay: %d base, +0 speed" % base, " ".join(s for s, _ in scene.log.lines))

    def test_the_report_is_up_the_moment_the_trace_completes(self):
        game, state, node, bot = self.node_scene("HUNT")
        state.trace = 99
        self.overtime(game, 1.0)                                # no key pressed
        over = game.scene
        self.assertIsInstance(over, scenes.GameOverScene)
        self.assertEqual([type(s).__name__ for s in game.stack], ["TitleScene", "GameOverScene"])
        self.assertEqual((state.over, state.trace, self.saved()["runs"]), ("traced", 100, 1))
        # a mistake that completes the trace does the same
        game, state, node, bot = self.node_scene("HUNT")
        state.trace = 99
        p = game.scene.puzzle
        taken = {s + j for s in p.solution for j in range(len(p.pattern))}
        bot.click(game.scene.hex.byte_rect(next(i for i in range(len(p.data)) if i not in taken)).center)
        game.frame(0.05)
        self.assertIsInstance(game.scene, scenes.GameOverScene)

    def test_the_report_types_out_then_disconnects(self):
        game, state, node, bot = self.node_scene("HUNT")
        title = game.stack[0]
        title.typing = None
        state.trace = 99
        self.overtime(game, 0.5)
        over = game.scene

        def lit(scene_y):
            """Is anything drawn on the text row at this layout y?"""
            row = game.screen.subsurface(ui.box((0, scene_y, ui.W, ui.lh())))
            return pygame.mask.from_threshold(row, (0, 0, 0), (1, 1, 1, 255)).count() < row.get_width() * row.get_height()

        bot.key(pygame.K_SPACE)                                 # too soon after the run ended: ignored
        for _ in range(6):
            game.frame(0.05)
        self.assertIsNotNone(over.typing)
        self.assertTrue(lit(90))                                # 0.3 s in: the heading is typed
        self.assertFalse(lit(ui.H - 40))                        # the last line is not there yet
        for _ in range(94):
            game.frame(0.05)
        self.assertIsNone(over.typing)
        self.assertTrue(lit(ui.H - 40))
        self.assertIsNone(over.dark)
        self.assertIs(game.scene, over)                         # 5 s in: still up, counting down
        for _ in range(210):
            game.frame(0.05)
        self.assertIsNotNone(over.dark)                         # 15 s: disconnected
        self.assertEqual(game.screen.get_at((ui.X(100), ui.Y(100)))[:3], ui.BLACK)
        self.assertFalse(any(lit(y) for y in range(0, ui.H - 20, 19)))      # the screen is dark
        for _ in range(30):
            if game.scene is title:
                break
            self.assertIs(game.scene, over)
            game.frame(0.05)
        self.assertIs(game.scene, title)                        # about a second later the title boots again,
        self.assertIsNotNone(title.typing)                     # typing itself out
        self.assertGreater(over.dark, 1.0)

        # a key finishes the typing; the next one disconnects at once
        game, state, node, bot = self.node_scene("HUNT")
        state.trace = 99
        self.overtime(game, 0.55)                               # the first overtime tick completes the trace
        over = game.scene
        for _ in range(9):                                      # past the moment keys are ignored
            game.frame(0.05)
        self.assertIsNotNone(over.typing)
        bot.key(pygame.K_SPACE)
        game.frame(0.05)
        self.assertIsNone(over.typing)
        self.assertIsNone(over.dark)
        bot.key(pygame.K_SPACE)
        game.frame(0.05)
        self.assertIsNotNone(over.dark)

    def test_the_title_types_itself_out_on_boot_only(self):
        game = main.Game(save_path=self.save_path, captures_dir=self.captures, seed=1)
        title, bot = game.scene, autoplay.Bot(game)

        def frame_pixels():
            return pygame.mask.from_threshold(game.screen, (0, 0, 0), (1, 1, 1, 255)).count()

        game.frame(0.02)
        self.assertIsNotNone(title.typing)
        partial = frame_pixels()                                # mostly black still
        for _ in range(100):
            game.frame(0.02)
        self.assertIsNone(title.typing)                        # typed out, fast: well under 2 s
        self.assertLess(frame_pixels(), partial)
        full = frame_pixels()
        # back from another screen: no typing
        bot.char("1")
        game.frame(0.02)
        self.assertIsInstance(game.scene, scenes.ModeScene)
        bot.key(pygame.K_ESCAPE)
        game.frame(0.02)
        self.assertIs(game.scene, title)
        self.assertIsNone(title.typing)
        # a key during the typing shows the rest at once, and still does its job
        title.boot()
        game.frame(0.02)
        bot.key(pygame.K_DOWN)
        game.frame(0.02)
        self.assertIsNone(title.typing)
        self.assertEqual(title.menu.index, 2)                   # moved down from TUTORIAL
        self.assertLessEqual(abs(frame_pixels() - full), 2500)  # all there (the cursor blinks, the selection moved)

    # ---- the menu on M, the logs on L

    def test_the_menu_opens_on_m_everywhere_but_inside_a_running_node(self):
        game = main.Game(save_path=self.save_path, captures_dir=self.captures, seed=1)
        bot, title = autoplay.Bot(game), game.scene

        def press(key, ch=""):
            bot.key(key, ch)
            game.frame(0.02)

        press(pygame.K_m, "m")
        menu = game.scene
        self.assertIsInstance(menu, scenes.MenuScene)
        self.assertIs(menu.under, title)
        self.assertEqual([it["label"] for it in menu.menu.items], ["KEYS", "TERMS", "LOGS", "FULLSCREEN: OFF"])
        press(pygame.K_m, "m")                              # M closes it again
        self.assertIs(game.scene, title)
        press(pygame.K_m, "m")
        press(pygame.K_ESCAPE)                              # so does ESC
        self.assertIs(game.scene, title)
        press(pygame.K_m, "m")
        bot.click((20, 780))                                # and a click outside it
        game.frame(0.02)
        self.assertIs(game.scene, title)

        # KEYS, then back
        press(pygame.K_m, "m")
        menu = game.scene
        press(ord("1"), "1")
        self.assertEqual(menu.page, "keys")
        self.assertTrue(any(keys == "M" for keys, _ in scenes.KEYBINDS))
        self.assertTrue(any(keys == "L" for keys, _ in scenes.KEYBINDS))
        press(pygame.K_ESCAPE)
        self.assertEqual((menu.page, game.scene), ("menu", menu))
        # LOGS goes to the logs, and leaving them lands where the menu was opened
        press(ord("3"), "3")
        self.assertIsInstance(game.scene, scenes.LogsScene)
        press(pygame.K_ESCAPE)
        self.assertIs(game.scene, title)

        # L is the logs directly; L again closes them
        press(pygame.K_l, "l")
        self.assertIsInstance(game.scene, scenes.LogsScene)
        press(pygame.K_l, "l")
        self.assertIs(game.scene, title)

        # in a node: fine at the briefing, not once the timer runs, fine again at the result
        game, state, node, bot = self.node_scene("HUNT")
        scene = game.scene
        self.assertEqual((scene.phase, scene.menu_ok), ("play", False))
        left = scene.left
        for key, ch in ((pygame.K_m, "m"), (pygame.K_l, "l")):
            bot.key(key, ch)
            game.frame(0.02)
            self.assertIs(game.scene, scene)
        self.assertLess(scene.left, left)                   # and the timer kept running
        self.overtime(game, 0.1)
        self.assertEqual((scene.phase, scene.menu_ok), ("play", False))     # not in overtime either
        bot.key(pygame.K_ESCAPE)
        game.frame(0.05)
        self.assertEqual((scene.phase, scene.menu_ok), ("result", True))
        # a practice node still opens on its briefing, and the menu is fine there
        brief = game.practice("HUNT", "RAW", 1)
        game.frame(0.02)
        self.assertEqual(brief.phase, "brief")
        bot.key(pygame.K_m, "m")
        game.frame(0.02)
        self.assertIsInstance(game.scene, scenes.MenuScene)
        bot.key(pygame.K_ESCAPE)
        game.frame(0.02)
        self.assertEqual((game.scene, brief.phase), (brief, "brief"))      # ESC closed the menu, not the node

    def test_the_screen_behind_the_menu_waits(self):
        game, state, node, bot = self.node_scene("HUNT")
        state.trace = 99
        game.scene.left = 0.01
        for _ in range(60):
            game.frame(0.05)
        over = game.scene
        self.assertIsInstance(over, scenes.GameOverScene)
        t = over.t
        bot.key(pygame.K_m, "m")
        for _ in range(100):                                # five seconds with the menu open
            game.frame(0.05)
        self.assertIsInstance(game.scene, scenes.MenuScene)
        self.assertEqual(over.t, t)                         # the countdown did not move
        bot.key(pygame.K_ESCAPE)
        game.frame(0.05)
        self.assertIs(game.scene, over)

    def test_terms_can_be_searched(self):
        game = main.Game(save_path=self.save_path, captures_dir=self.captures, seed=1)
        bot = autoplay.Bot(game)
        bot.key(pygame.K_m, "m")
        game.frame(0.02)
        menu = game.scene
        bot.char("2")
        game.frame(0.02)
        self.assertEqual((menu.page, menu.query), ("terms", ""))
        everything = menu.term_lines()
        self.assertEqual(sum(colour != "fg" for _, colour in everything), len(glossary.TERMS))
        for ch in "tool sl":                                # every letter is typed, L included: no hotkeys in here
            bot.char(ch) if ch != " " else bot.key(pygame.K_SPACE, " ")
        game.frame(0.02)
        self.assertEqual((game.scene, menu.page, menu.query), (menu, "terms", "tool sl"))
        lines = menu.term_lines()
        self.assertTrue(lines[0][0].startswith("tool slots"))
        self.assertIn("not a real term", lines[0][0])       # and it says the word is the game's
        self.assertLess(len(lines), len(everything))
        for ch in "mmm":
            bot.char(ch)
        game.frame(0.02)
        self.assertEqual((game.scene, menu.query, menu.term_lines()), (menu, "tool slmmm", []))
        for _ in range(20):
            bot.key(pygame.K_BACKSPACE)
        game.frame(0.02)
        self.assertEqual(menu.query, "")
        bot.key(pygame.K_PAGEDOWN)
        game.frame(0.02)
        self.assertEqual(menu.scroll, menu.rows)
        for _ in range(60):
            bot.key(pygame.K_PAGEDOWN)
        game.frame(0.02)
        self.assertEqual(menu.scroll, len(everything) - menu.rows)      # stops at the end
        bot.key(pygame.K_ESCAPE)
        game.frame(0.02)
        self.assertEqual((game.scene, menu.page), (menu, "menu"))

    def test_the_glossary(self):
        terms = [t for t, _, _ in glossary.TERMS]
        self.assertEqual(len(terms), len({t.lower() for t in terms}))
        self.assertGreater(len(terms), 60)
        for term, text, real in glossary.TERMS:
            self.assertTrue(20 <= len(text) <= 200, term)
            self.assertTrue(text.endswith("."), term)
        game_words = {t for t, _, real in glossary.TERMS if not real}
        self.assertTrue({"credits", "tool slots", "black market", "TRACE", "jack in", "footprint"} <= game_words)
        self.assertFalse({"checksum", "XOR", "IDS", "foothold", "file carving"} & game_words)
        for kind in puzzles.REGISTRY:                       # every node type has an entry
            self.assertIn("%s (node)" % kind, terms)
        names = [t for t, _, _ in glossary.search("")]
        self.assertEqual(names, sorted(names, key=str.lower))
        self.assertEqual(glossary.search("check")[0][0], "checksum")            # a term that starts with it first
        self.assertIn("pseudo-header", [t for t, _, _ in glossary.search("checksum")])     # then definitions
        self.assertEqual(glossary.search("zzzz"), [])
        self.assertEqual(glossary.search("  XOR ")[0][0], "XOR")

    # ---- highlighting text by dragging over it

    def drag(self, game, bot, a, b):
        bot.move(a)
        bot.down(a)
        bot.move(((a[0] + b[0]) // 2, (a[1] + b[1]) // 2))
        bot.move(b)
        bot.up(b)
        game.frame(0.02)

    def test_dragging_highlights_text_like_a_terminal(self):
        game = main.Game(save_path=self.save_path, captures_dir=self.captures, seed=1)
        bot, title = autoplay.Bot(game), game.scene
        title.typing = None
        game.frame(0.02)
        x, y, cw = title.X, title.menu.bottom + 30, ui.cw()            # the heading OPERATOR RECORD
        a, b = (x + 9 * cw + 2, y + 5), (x + 15 * cw - 2, y + 5)        # "RECORD"
        self.drag(game, bot, a, b)
        self.assertEqual(game.marked_text(), "RECORD")
        self.assertIs(game.scene, title)                    # a drag clicks nothing
        cell = (ui.X(x + 12 * cw), ui.Y(y))
        self.assertEqual(game.screen.get_at(cell)[:3], ui.MARK)
        self.assertEqual(game.screen.get_at((ui.X(x + 8 * cw), ui.Y(y)))[:3], ui.BLACK)
        self.assertEqual(game.copy_marked(), "RECORD")                  # cmd+C puts this on the clipboard
        # across lines, dragging upwards: from the point on the top line to its end,
        # all of those between, and the bottom line up to where the drag began
        first = title.menu.item_rect(0)
        self.drag(game, bot, (x + 8 * cw - 2, y + 5), (first.x + 10 * ui.cw(18) + 2, first.y + 5))
        lines = game.marked_text().split("\n")
        self.assertEqual(lines[0], "RUN")
        self.assertEqual(lines[1:], ["  [2] TUTORIAL", "  [3] LOGS", "  [M] MENU", "OPERATOR"])
        self.assertIs(game.scene, title)                    # the drag ended on NEW RUN and did not start one
        # the next press clears it; and a plain click still clicks
        bot.down((600, 700))
        game.frame(0.02)
        self.assertEqual(game.marked_text(), "")
        bot.up((600, 700))
        bot.click(first.center)
        game.frame(0.02)
        self.assertIsInstance(game.scene, scenes.ModeScene)
        # what is highlighted goes when the screen does
        self.drag(game, bot, (80, 85), (300, 85))
        self.assertEqual(game.marked_text(), "SELECT DATA MODE")
        bot.key(pygame.K_ESCAPE)
        game.frame(0.02)
        game.frame(0.02)
        self.assertEqual(game.marked_text(), "")

    def test_a_drag_over_bytes_is_not_a_guess(self):
        game, state, node, bot = self.node_scene("HUNT")
        scene, p = game.scene, game.scene.puzzle
        hx = scene.hex
        self.assertFalse(scene.owns_drag(hx.byte_rect(3).center))          # HUNT picks by clicking
        self.drag(game, bot, hx.byte_rect(3).center, hx.byte_rect(9).center)
        self.assertEqual((p.mistakes, len(p.found), state.trace), (0, 0, 0))
        self.assertIn("%02X" % p.data[5], game.marked_text())
        bot.click(hx.byte_rect(p.solution[0]).center)       # a click is still a pick
        game.frame(0.02)
        self.assertEqual(len(p.found), 1)
        # where dragging is the puzzle's own input, the puzzle gets it
        game = main.Game(save_path=self.save_path, captures_dir=self.captures, seed=4)
        scene = game.practice("DISSECT", "PROTOCOL", 1)
        bot = autoplay.Bot(game)
        bot.key(pygame.K_SPACE)
        game.frame(0.02)
        lo, hi = scene.puzzle.solution[0]
        self.assertTrue(scene.owns_drag(scene.hex.byte_rect(lo).center))
        self.drag(game, bot, scene.hex.byte_rect(lo).center, scene.hex.byte_rect(hi).center)
        self.assertEqual((scene.puzzle.round, scene.puzzle.mistakes, game.marked_text()), (1, 0, ""))

    def test_marking_follows_reading_order(self):
        ui.begin_frame()
        for y, text in ((100, "first line"), (119, "second line"), (138, "third line")):
            ui.runs.append((50, y, text, 16))
        cw = ui.cw()
        pick = lambda a, b: ui.marked_text(a, b)
        self.assertEqual(pick((50 + 6 * cw, 105), (50 + 5 * cw, 143)), "line\nsecond line\nthird")
        self.assertEqual(pick((50 + 5 * cw, 143), (50 + 6 * cw, 105)), "line\nsecond line\nthird")  # dragged upwards
        self.assertEqual(pick((50 + 7 * cw, 124), (50, 124)), "second l")                              # leftwards
        self.assertEqual(pick((900, 105), (20, 124)), "")                                              # past both ends
        self.assertEqual(pick((0, 0), (2000, 2000)), "first line\nsecond line\nthird line")
        ui.forget((50 + 2 * cw, 122, 4 * cw, 10))           # a popover over "cond" in the second line
        self.assertEqual(pick((0, 0), (2000, 2000)), "first line\nse     line\nthird line")
        ui.begin_frame()
        self.assertEqual(pick((0, 0), (2000, 2000)), "")

    # ---- every new window types itself out

    def test_a_new_window_types_itself_out_and_a_returning_one_does_not(self):
        game = main.Game(save_path=self.save_path, captures_dir=self.captures, seed=1)
        bot, title = autoplay.Bot(game), game.scene
        title.typing = None
        opened = []
        for key, kind in ((("1", ), scenes.ModeScene), (("2", ), scenes.ToolkitScene), (("1", ), scenes.MapScene)):
            bot.char(key[0])
            game.frame(0.02)
            scene = game.scene
            self.assertIsInstance(scene, kind)
            self.assertIsNotNone(scene.typing, kind.__name__)       # just appeared: typing
            opened.append(scene)
            for _ in range(100):
                if scene.typing is None:
                    break
                game.frame(0.02)
            self.assertIsNone(scene.typing, kind.__name__)          # all there within two seconds
        board = opened[-1]
        for key, kind in (((pygame.K_m, "m"), scenes.MenuScene), ((pygame.K_l, "l"), scenes.LogsScene)):
            bot.key(*key)
            game.frame(0.02)
            self.assertIsInstance(game.scene, kind)
            self.assertIsNotNone(game.scene.typing)
            bot.key(pygame.K_ESCAPE)                        # a key shows the rest and still does its job
            game.frame(0.02)
            self.assertIs(game.scene, board)
            self.assertIsNone(board.typing)                 # the map was already there: it is not typed again
        node = board.run.available()[0]
        bot.click(board.node_rects[node.id].center)
        game.frame(0.02)
        self.assertEqual((type(game.scene), game.scene.phase), (scenes.PuzzleScene, "play"))
        self.assertIsNotNone(game.scene.typing)             # a node is a new window too

    def test_tools_are_real_kinds_of_software(self):
        self.assertEqual(sorted(tools.STARTERS + tools.UNLOCK_ORDER), sorted(tools.TOOLS))
        self.assertEqual(set(tools.COUNTERS), set(puzzles.MODIFIERS))
        for tool in tools.TOOLS.values():
            self.assertLessEqual(len(tool.id), 10, tool.id)             # fits the "%-10s" columns
            self.assertLessEqual(len(tool.desc), 98, tool.id)           # fits beside its name on the map
        self.assertTrue(set(tools.RENAMED.values()) <= set(tools.TOOLS))
        self.assertFalse(set(tools.RENAMED) & set(tools.TOOLS))
        # the words that were not real are gone from everything the player reads
        import ast
        import re
        root = os.path.dirname(os.path.abspath(main.__file__))
        for name in ("scenes.py", "tools.py", "run.py", "autoplay.py", "puzzles/ids.py", "puzzles/alertlog.py",
                     "puzzles/payload.py",
                     "puzzles/hunt.py", "puzzles/xor.py", "puzzles/dissect.py", "puzzles/checksum.py",
                     "puzzles/carve.py", "glossary.py"):
            with open(os.path.join(root, name)) as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    self.assertIsNone(re.search(r"\bRAM\b|\bICE\b|\bCACHE\b|\bcaches?\b", node.value, re.I),
                                      (name, node.value))

    def test_traceable_tools_leave_a_footprint(self):
        loud = [t.id for t in tools.TOOLS.values() if t.traceable]
        self.assertEqual(sorted(loud), ["BRUTEFORCE", "EXPLOIT", "LOGWIPE", "MINER", "SCANNER"])
        quiet = [t for t in tools.TOOLS if t not in loud]
        self.assertEqual(tools.footprint(quiet), 0)
        for n in range(len(loud) + 1):
            held = quiet[:2] + loud[:n]
            self.assertAlmostEqual(tools.footprint(held), 0.1 * n)
            self.assertAlmostEqual(tools.trace_cost(held, 10, "mistake"), 10 * (1 + 0.1 * n))
            self.assertAlmostEqual(tools.trace_cost(held, 20, "timeout"), 20 * (1 + 0.1 * n))
        self.assertEqual(tools.trace_cost(["FIREWALL", "MINER"], 20, "timeout"), 11)    # halved, then +10%
        self.assertEqual(tools.trace_cost(["SPOOFER", "MINER"], 10, "mistake", first_mistake=True), 0)
        for t in tools.TOOLS:
            self.assertEqual(tools.describe(t).endswith(tools.TRACEABLE_NOTE), t in loud, t)
        # in a node: the same mistake costs more with a miner aboard, and the briefing says so
        costs = {}
        for held in ((), ("MINER", "SCANNER")):
            game = main.Game(save_path=self.save_path, captures_dir=self.captures, seed=9)
            scene = game.practice("HUNT", "RAW", 3)
            for t in held:
                scene.run.install(t)
            bot = autoplay.Bot(game)
            bot.key(pygame.K_SPACE)
            game.frame(0.05)
            p = scene.puzzle
            taken = {s + j for s in p.solution for j in range(len(p.pattern))}
            spot = next(i for i in range(len(p.data)) if i not in taken and p.judge(i) == puzzles.WILD)
            bot.click(scene.hex.byte_rect(spot).center)
            game.frame(0.05)
            costs[held] = scene.run.trace
        self.assertAlmostEqual(costs[("MINER", "SCANNER")], costs[()] * 1.2)

    def test_bars_are_drawn_the_way_a_terminal_draws_them(self):
        for frac, want in ((0, "[          ]"), (0.5, "[|||||     ]"), (1, "[||||||||||]"), (7, "[||||||||||]")):
            self.assertEqual(ui.bar(frac, 10), want)
        with open(os.path.join(os.path.dirname(os.path.abspath(main.__file__)), "ui.py"), encoding="utf-8") as fh:
            source = fh.read()
        self.assertNotIn("\u2588", source)                 # no solid or shaded block characters
        self.assertNotIn("\u2591", source)

    def test_the_log_does_not_repeat_itself(self):
        log = ui.Log()
        for line in ("a", "a", "a", "b", "a"):
            log.add(line)
        log.add("a", "red")                                 # the same words in another colour are another line
        self.assertEqual([s for s, _ in log.lines], ["a", "b", "a", "a"])

    def test_a_log_counts_repeats_wraps_and_scrolls(self):
        heard = []
        log = ui.Log(echo=lambda s, c: heard.append(s))
        for line in ("a", "a", "a", "b"):
            log.add(line)
        self.assertEqual(log.rows(), [("> a  (x3)", "fg"), ("> b", "fg")])     # said three times, shown once
        self.assertEqual(heard, ["a", "a", "a", "b"])                           # but passed on every time
        log.add("one two three four five six seven eight nine ten", "red")
        self.assertEqual(log.rows(22), [("> a  (x3)", "fg"), ("> b", "fg"), ("> one two three four", "red"),
                                        ("  five six seven eight", "red"), ("  nine ten", "red")])
        log.scroll_by(1, 2, 22)
        self.assertEqual(log.scroll, 1)
        log.scroll_by(99, 2, 22)
        self.assertEqual(log.scroll, 3)             # stops with the oldest row at the top
        log.scroll_by(-99, 2, 22)
        self.assertEqual(log.scroll, 0)
        log.scroll_by(5, 9, 22)
        self.assertEqual(log.scroll, 0)             # it all fits: nothing to scroll
        log.scroll_by(2, 2, 22)
        log.add("c")
        self.assertEqual(log.scroll, 0)             # something new shows the latest again

    def test_the_map_keeps_a_session_log_and_the_tools_sit_on_the_right(self):
        game, state, node, bot = self.node_scene("HUNT")
        board, scene = game.stack[-2], game.scene
        state.install("MINER")
        p = scene.puzzle
        taken = {s + j for s in p.solution for j in range(len(p.pattern))}
        bot.click(scene.hex.byte_rect(next(i for i in range(len(p.data)) if i not in taken)).center)
        game.frame(0.05)
        scene._end("solved")
        bot.key(pygame.K_SPACE)
        for _ in range(60):
            game.frame(0.05)                        # back on the map, and long enough for it to type itself out
        self.assertIs(game.scene, board)
        self.assertIsNone(board.typing)
        said = [s for s, _ in board.log.lines]
        self.assertIn("jacked in: HUNT %s" % node.name, said)                  # what happened in the node is here
        self.assertTrue(any(s.startswith("TRACE +") for s in said), said)
        self.assertTrue(any(s.startswith("NODE BREACHED") for s in said), said)
        self.assertLess(said.index("jacked in: HUNT %s" % node.name), len(said) - 1)
        # the tools are bottom right with what they do; the log is on the left and scrolls
        drawn = {s: (x, y) for x, y, s, _ in ui.runs}
        tools_x, log_x = drawn["TOOLS 1/3  footprint +10%"][0], drawn["SESSION LOG"][0]
        self.assertGreater(tools_x, ui.W / 2)
        self.assertLess(log_x, ui.W / 4)
        self.assertGreater(drawn["SESSION LOG"][1], board.Y + runmod.SLOTS * scenes.SLOT_H * ui.lh(scenes.MAP_SIZE))
        self.assertTrue(any(s.startswith("Leaves a miner") and x == tools_x for s, (x, y) in drawn.items()))
        top, _, width, _, rows = board._panels()
        for i in range(3 * rows):
            state.note("line %d" % i)
        game.frame(0.05)
        self.assertEqual(board.log.scroll, 0)
        self.assertIn("> line %d" % (3 * rows - 1), {s for _, _, s, _ in ui.runs})
        bot.key(pygame.K_PAGEUP)
        game.frame(0.05)
        self.assertEqual(board.log.scroll, rows)
        shown = {s for _, _, s, _ in ui.runs}
        self.assertIn("> line %d" % (2 * rows - 1), shown)
        self.assertNotIn("> line %d" % (3 * rows - 1), shown)
        self.assertIn("%d newer below" % rows, shown)
        bot.wheel(1)
        game.frame(0.05)
        self.assertEqual(board.log.scroll, rows + 2)
        bot.key(pygame.K_HOME)
        game.frame(0.05)
        self.assertEqual(board.log.scroll, len(board.log.rows(width)) - rows)
        bot.key(pygame.K_END)
        game.frame(0.05)
        self.assertEqual(board.log.scroll, 0)
        self.assertIs(game.scene, board)                                        # none of that left the map

    def test_carve_answers_are_the_names_in_the_signature_table(self):
        for seed in range(6):
            p = puzzles.generate("CARVE", seed, sources.RandomSource(), 1 + seed)
            self.assertEqual(p.click(p.files[0][0]), "ok")
            rows = [entry[0] for entry in p.panel()]
            table = [s.split()[0] for s in rows[rows.index("KNOWN SIGNATURES") + 1:]]
            offered = [s.split("] ")[1] for s in rows if s.startswith("  [")]
            self.assertEqual(len(offered), len(p.pool))
            self.assertEqual(offered, p.options[0])
            self.assertTrue(set(offered) <= set(table), (offered, table))       # EXE, not "Windows executable"

    def test_the_briefing_is_one_box_of_short_rows_beside_an_example(self):
        game = main.Game(save_path=self.save_path, captures_dir=self.captures, seed=9)
        for kind, mode in (("CARVE", "RAW"), ("HUNT", "RAW"), ("PAYLOAD", "RAW"), ("XOR", "PROTOCOL"),
                           ("DISSECT", "PROTOCOL"), ("CHECKSUM", "PROTOCOL"), ("REASSEMBLE", "RAW"), ("IDS", "PROTOCOL")):
            scene = game.practice(kind, mode, 3)
            for _ in range(80):
                game.frame(0.02)
            self.assertEqual((scene.phase, scene.typing), ("brief", None))
            inside = [(x, s) for x, y, s, _ in ui.runs if y >= scene.HEX_Y and y < scene.LOG_Y]
            said = [s for _, s in inside]
            for label in ("DO", "TIME", "PAYS"):         # the numbers are in the same box
                self.assertIn(label, said, kind)
            state = scene.run
            ranks = scene.puzzle.ranks() if kind != "IDS" else []
            for name, mult in ranks or [("", 1.0)]:        # a kind with ranks says what each pays
                factor = scene.factor * mult
                low = state.reward(kind, 0, scene.level, 99, factor)
                high = state.reward(kind, 1, scene.level, factor=factor)
                self.assertLess(low, high)
                want = "%s %d to %d" % (name.split()[0], low, high) if name else "%d to %d credits" % (low, high)
                self.assertTrue(any(want in s for s in said), (kind, want, said))
            self.assertIn("%ds" % scene.total, said)
            self.assertTrue(all(len(s) <= 64 for s in said), (kind, max(said, key=len)))    # no wall of text
            self.assertLessEqual(len(said), 40, kind)
            self.assertFalse(any("pays more" in s for s in said), kind)         # the pay is two numbers, no advice
            # the example is on the right, where the side panel will be, and nothing else is
            right = [s for x, s in inside if x >= scene.PANEL_X]
            self.assertTrue(right and right[0].startswith("EXAMPLE"), (kind, right))
            self.assertGreater(len(right), 2, kind)
            self.assertFalse(set(right) & {"DO", "TIME", "PAYS"}, kind)
            self.assertTrue(all(x + len(s) * ui.cw() <= scene.PANEL_X for x, s in inside if s not in right), kind)
            # it is an animation: it changes as the briefing stays up, and comes back round to where it began
            loop = sum(secs for secs, _ in scene.puzzle.example())
            seen = set()
            for _ in range(int(loop / 0.1) + 2):
                game.frame(0.1)
                seen.add(tuple((x, s) for x, y, s, _ in ui.runs if x >= scene.PANEL_X and scene.HEX_Y <= y < scene.LOG_Y))
            self.assertGreaterEqual(len(seen), 4, kind)
            scene.briefed = 0.0
            game.frame(0)
            first = [s for x, y, s, _ in ui.runs if x >= scene.PANEL_X and scene.HEX_Y <= y < scene.LOG_Y]
            scene.briefed = loop
            game.frame(0)
            self.assertEqual([s for x, y, s, _ in ui.runs if x >= scene.PANEL_X and scene.HEX_Y <= y < scene.LOG_Y], first)
            self.assertEqual(scene.phase, "brief")
            game.pop()

    def test_the_timer_is_a_number_of_whole_seconds(self):
        game, state, node, bot = self.node_scene("HUNT")
        scene = game.scene
        state.install("PROXY")
        scene.charges = tools.node_charges(state.tools)
        for _ in range(7):
            game.frame(0.1)
        clock = [s for _, _, s, _ in ui.runs if s.startswith("TIME")]
        self.assertEqual(clock, ["TIME %ds" % math.ceil(scene.left)])
        self.assertLess(scene.left, scene.total)
        self.assertNotIn("[", clock[0])                     # no bar
        self.assertNotIn(".", clock[0])                     # no tenths
        scene.activate("PROXY")
        game.frame(0.1)
        clock = [s for _, _, s, _ in ui.runs if s.startswith("TIME")]
        self.assertEqual(clock, ["TIME %ds  PAUSED 10s" % math.ceil(scene.left)])

    def test_fast_and_clean_pays_more_and_never_less_than_the_base(self):
        state = runmod.RunState("RAW", sources.RandomSource(), 1)
        for kind in list(puzzles.REGISTRY) + ["IDS"]:
            for level in (1, 3.5, 6):
                base, speed, clean = state.score(kind, 1, level)
                self.assertTrue(base > 0 and speed > 0 and clean > 0, kind)
                self.assertEqual(state.reward(kind, 1, level), base + speed + clean)
                pays = [state.reward(kind, 1, level, mistakes) for mistakes in range(12)]
                self.assertEqual(pays, sorted(pays, reverse=True), kind)       # every mistake costs, or costs nothing
                self.assertGreater(pays[0], pays[1], kind)
                self.assertEqual(pays[-1], base + speed, kind)                  # the accuracy bonus stops at zero
                self.assertGreater(state.reward(kind, 1, level), state.reward(kind, 0.2, level), kind)   # speed pays
                self.assertEqual(state.reward(kind, 0, level, 99), base, kind)  # slow and sloppy: the base, no less
        # in a node: a mistake comes off the pay, and SNAPSHOT puts it back
        game, state, node, bot = self.node_scene("HUNT")
        scene, p = game.scene, game.scene.puzzle
        state.install("SNAPSHOT")
        scene.charges = tools.node_charges(state.tools)
        taken = {s + j for s in p.solution for j in range(len(p.pattern))}
        miss = scene.hex.byte_rect(next(i for i in range(len(p.data)) if i not in taken)).center
        for _ in range(2):
            bot.click(miss)
            game.frame(0.05)
        self.assertEqual(scene.mistakes, 2)
        scene.activate("SNAPSHOT")
        self.assertEqual(scene.mistakes, 1)
        before, quick = state.credits, scene.left / scene.total
        scene._end("solved")
        self.assertEqual(state.credits - before, state.reward("HUNT", quick, scene.level, 1, scene.factor))
        self.assertLess(state.credits - before, state.reward("HUNT", quick, scene.level, 0, scene.factor))
        base, speed, clean = state.score("HUNT", quick, scene.level, 1, scene.factor)
        self.assertIn("pay: %d base, +%d speed, +%d accuracy" % (base, speed, clean), [s for s, _ in scene.log.lines])

    def test_how_to_work_a_menu_is_in_the_menu_not_on_the_title(self):
        game = main.Game(save_path=self.save_path, captures_dir=self.captures, seed=1)
        for _ in range(80):
            game.frame(0.02)
        shown = [s for _, _, s, _ in ui.runs]
        self.assertFalse(any("M menu" in s or "arrows" in s for s in shown), shown)
        keys = " ".join(k for k, does in scenes.KEYBINDS if does)
        for words in ("arrows + ENTER", "number key", "mouse"):
            self.assertIn(words, keys)

    def test_a_foothold_clears_logs_or_mines_a_little(self):
        game, state, node, bot = self.node_scene("HUNT")
        game.scene.back_out()
        for choice, trace, credits in (("1", 40 - runmod.FOOTHOLD_TRACE, 0), ("2", 40, runmod.FOOTHOLD_CREDITS)):
            hold = runmod.Node(node.layer, node.slot, "FOOTHOLD", "10.9.9.9:22", 5)
            state.trace, before = 40, state.credits
            state.move_to(hold)
            game.push(scenes.FootholdScene(game, state, hold))
            self.assertEqual([it["label"] for it in game.scene.menu.items], ["CLEAR LOGS", "MINE"])
            bot.char(choice)
            game.frame(0.02)
            self.assertIsInstance(game.scene, scenes.MapScene)
            self.assertEqual((state.trace, state.credits - before, hold.done), (trace, credits, True))
            state.back_out()

    def test_the_tutorial_says_which_words_are_real(self):
        game = main.Game(save_path=self.save_path, captures_dir=self.captures, seed=1)
        text = " ".join(scenes.TutorialScene(game).steps[-1]["text"])
        for phrase in ("tools", "really called", "traceable", "tool slots", "Credits", "black market", "not real"):
            self.assertIn(phrase, text)

    def test_a_save_from_before_the_renames_still_loads(self):
        with open(self.save_path, "w") as fh:
            json.dump({"version": 1, "runs": 6, "ice_kills": 4, "tutorial": True,
                       "best_solve": {"HUNT": 28.3, "MAGIC": 24.8, "BREACH": 31.0},
                       "magic": {"JPEG": {"count": 2, "hex": "FF D8 FF E0"}, "GIF": {"count": 1, "hex": "47 49 46"}},
                       "unlocked": ["WILDCARD", "FREEZE", "ROLLBACK", "SIPHON", "PARSER", "ASCII", "PING", "GHOST"]}, fh)
        game = main.Game(save_path=self.save_path, captures_dir=self.captures, seed=1)
        data = game.save.data
        self.assertEqual((data["runs"], data["ids_evaded"], data["tutorial"]), (6, 4, True))
        self.assertEqual(data["best_solve"], {"HUNT": 28.3, "CARVE": 24.8, "PAYLOAD": 31.0})
        self.assertEqual(sorted(data["signatures"]), ["GIF", "JPEG"])
        for _ in range(60):
            game.frame(0.02)                                # the title counts only signatures still in the game
        game.push(scenes.LogsScene(game))
        game.scene.tab = len(game.scene.tabs) - 1
        game.frame(0.02)                                    # and the FILES page copes with the old ones
        game.pop()
        self.assertEqual(data["unlocked"], ["BRUTEFORCE", "PROXY", "SNAPSHOT", "MINER", "DISSECTOR", "STRINGS",
                                            "SCANNER", "SPOOFER", "VPN", "CODEPAGE"])  # starters added later
        self.assertEqual(game.save.unlock_next(), "LOGWIPE")                # and unlocking carries on from there

    def test_a_vpn_hides_you_but_costs_speed(self):
        self.assertIn("VPN", tools.STARTERS)
        self.assertFalse(tools.TOOLS["VPN"].traceable)
        self.assertEqual(tools.trace_cost(["VPN"], 20, "mistake"), 15)              # a quarter off every gain
        self.assertEqual(tools.trace_cost(["VPN"], 20, "timeout"), 15)
        self.assertEqual(tools.trace_cost(["VPN", "MINER"], 20, "mistake"), 16.5)   # then the footprint on top
        self.assertEqual(tools.time_limit(["VPN"], 60), 54)
        self.assertEqual(tools.time_limit(["PROXY"], 60), 60)
        # in a node: less time on the clock, and a mistake that costs less
        game = main.Game(save_path=self.save_path, captures_dir=self.captures, seed=9)
        plain = game.practice("HUNT", "RAW", 3)
        plain.run.install("VPN")
        tunnel = scenes.PuzzleScene.open(game, plain.run, plain.node, plain.level)
        self.assertAlmostEqual(tunnel.total, plain.total * 0.9)
        game.replace(tunnel)
        bot = autoplay.Bot(game)
        bot.key(pygame.K_SPACE)
        game.frame(0.05)
        p = tunnel.puzzle
        taken = {s + j for s in p.solution for j in range(len(p.pattern))}
        spot = next(i for i in range(len(p.data)) if i not in taken and p.judge(i) == puzzles.WILD)
        bot.click(tunnel.hex.byte_rect(spot).center)
        game.frame(0.05)
        self.assertAlmostEqual(tunnel.run.trace, round(tunnel.mistake_range[1] * 0.75, 1))

    def test_a_mistake_costs_by_how_bad_it_was(self):
        game, state, node, bot = self.node_scene("HUNT")
        scene, p = game.scene, game.scene.puzzle
        taken = {s + j for s in p.solution for j in range(len(p.pattern))}
        spots = {}
        for i in range(len(p.data)):
            if i not in taken:
                spots.setdefault(p.judge(i), i)
        self.assertTrue({puzzles.NEAR, puzzles.WILD} <= set(spots))     # a small random dump may have no in-between
        costs = {s: state.mistake_cost(scene.level, s) for s in (puzzles.NEAR, puzzles.WRONG, puzzles.WILD)}
        self.assertLess(costs[puzzles.NEAR], costs[puzzles.WRONG])
        self.assertLess(costs[puzzles.WRONG], costs[puzzles.WILD])
        self.assertEqual(scene.mistake_range, (costs[puzzles.NEAR], costs[puzzles.WILD]))
        for severity, note in ((puzzles.NEAR, "near miss"), (puzzles.WRONG, ""), (puzzles.WILD, "wild guess")):
            if severity not in spots:
                continue
            before = state.trace
            bot.click(scene.hex.byte_rect(spots[severity]).center)
            game.frame(0.05)
            self.assertEqual(state.trace - before, costs[severity], severity)
            line = [s for s, _ in scene.log.lines if s.startswith("TRACE +")][-1]
            self.assertEqual(line, ("TRACE +%d%%  %s" % (costs[severity], note)).rstrip())
        self.assertEqual(state.stats["mistakes"], len(spots))

    def test_nothing_shakes_when_trace_rises(self):
        self.assertFalse(hasattr(hexview.HexView, "glitch"))
        game, state, node, bot = self.node_scene("HUNT")
        scene = game.scene
        state.trace = 80                                        # "running hot" used to glitch at random too
        p = scene.puzzle
        taken = {s + j for s in p.solution for j in range(len(p.pattern))}
        bot.click(scene.hex.byte_rect(next(i for i in range(len(p.data)) if i not in taken)).center)
        for _ in range(200):
            game.frame(0.05)
            if scene.phase != "play":
                break
            self.assertEqual(scene.hex._lost, set())
        self.assertEqual(state.stats["mistakes"], 1)
        self.assertNotIn("glitch", tools.TOOLS["FILTER"].desc)

    def test_ids_effects_are_steady(self):
        hx = hexview.HexView(0, 0)
        hx.data = bytes(range(200))
        hx.loss = hx.throttle = True
        hx.update(0.1)
        lost = set(hx._lost)
        self.assertEqual(len(lost), round(200 * hexview.LOSS_SHARE))
        hx.update(0.1)
        self.assertEqual(hx._lost, lost)                        # no flicker between frames
        self.assertLess(hx._loaded, len(hx.data))               # still arriving

    def test_map_opens_the_shop(self):
        game = main.Game(save_path=self.save_path, captures_dir=self.captures, seed=11)
        state = runmod.RunState("RAW", sources.RandomSource(), 11)
        state.credits = 1000
        game.run_state = state
        game.push(scenes.MapScene(game, state))
        bot = autoplay.Bot(game, solve=False, pace=1)
        game.frame(0.05)
        bot.key(pygame.K_b)
        game.frame(0.05)
        self.assertIsInstance(game.scene, scenes.ShopScene)
        bought = state.market()["stock"][0]
        for _ in range(100):
            game.frame(0.05)                                    # let it type itself out
        bot.key(pygame.K_RETURN)
        game.frame(0.05)
        self.assertIn(bought, state.tools)
        bot.key(pygame.K_ESCAPE)
        game.frame(0.05)
        self.assertIsInstance(game.scene, scenes.MapScene)
        self.assertNotIn(bought, state.market()["stock"])      # the market keeps its stock between visits

    def test_the_path_line(self):
        home = os.path.expanduser("~")
        self.assertEqual(scenes.HERE, os.path.dirname(os.path.abspath(main.__file__)))
        state = runmod.RunState("PROTOCOL", sources.SynthSource(), 3)
        self.assertEqual([name for name, _ in scenes.run_crumbs(state)], ["protocol", "subnet1"])
        self.assertEqual([name for name, _ in scenes.run_crumbs(state, None, None, "10.0.0.1:22", "hunt")],
                         ["protocol", "subnet1", "10.0.0.1:22", "hunt"])
        self.assertEqual(ui.fit_path("/a/b/c", 20), "/a/b/c")
        long = home + "/games/hexbreach/protocol/subnet3/10.0.0.1:22/ids"
        self.assertEqual(ui.fit_path(long, len(long)), long)
        self.assertEqual(ui.fit_path(long, len(long) - 1), "~" + long[len(home):])
        cut = ui.fit_path(long, 30)
        self.assertEqual((len(cut), cut[0], cut.endswith("/ids")), (30, "\u2026", True))
        with open(os.path.join(os.path.dirname(scenes.HERE + "/x"), "scenes.py")) as fh:
            self.assertNotIn("where you live", fh.read())

    # ---- going back: ESC, or a click on a level of the path line

    def crumb(self, game, name):
        """Where to click for a level of the path, or None if it cannot be clicked."""
        game.frame(0.02)
        return next((rect.center for rect, label, _ in game.scene.path.hits if label == name), None)

    def at_loadout(self, mode="PROTOCOL"):
        game = main.Game(save_path=self.save_path, captures_dir=self.captures, seed=6)
        bot = autoplay.Bot(game)
        bot.char("1")
        game.frame(0.02)
        bot.char(str(["RAW", "PROTOCOL", "LIVE"].index(mode) + 1))
        game.frame(0.02)
        self.assertIsInstance(game.scene, scenes.ToolkitScene)
        return game, bot

    def test_back_from_the_loadout(self):
        root = os.path.basename(scenes.HERE)
        for how in ("esc", "protocol", root):
            game, bot = self.at_loadout()
            title = game.stack[0]
            self.assertEqual([self.crumb(game, n) is not None for n in (root, "protocol", "loadout")],
                             [True, True, False])           # where you are is not a link
            if how == "esc":
                bot.key(pygame.K_ESCAPE)
            else:
                bot.click(self.crumb(game, how))
            game.frame(0.02)
            if how == root:
                self.assertIs(game.scene, title)            # all the way out
            else:
                self.assertIsInstance(game.scene, scenes.ModeScene)     # one level up, on the mode it came from
                self.assertEqual(game.scene.menu.items[game.scene.menu.index]["label"], "PROTOCOL")
                self.assertEqual(len(game.stack), 2)
                bot.key(pygame.K_ESCAPE)
                game.frame(0.02)
                self.assertIs(game.scene, title)
            self.assertFalse(os.path.exists(self.save_path) and self.saved()["runs"])   # no run was played

    def test_the_hovered_level_lights_up(self):
        game, bot = self.at_loadout()
        pos = self.crumb(game, "protocol")
        rect = next(r for r, label, _ in game.scene.path.hits if label == "protocol")
        corner = (ui.X(rect.x), ui.Y(rect.y))
        self.assertEqual(game.screen.get_at(corner)[:3], ui.BLACK)
        bot.move(pos)
        game.frame(0.02)
        game.frame(0.02)
        self.assertEqual(game.screen.get_at(corner)[:3], ui.TAN)
        game.scene.path.lit = ("protocol", time.monotonic() - ui.BLINK * 1.5)      # and blinks like any cursor
        game.frame(0.02)
        self.assertEqual(game.screen.get_at(corner)[:3], ui.BLACK)
        bot.move((600, 400))
        game.frame(0.02)
        game.frame(0.02)
        self.assertEqual(game.screen.get_at(corner)[:3], ui.BLACK)

    def test_no_way_out_of_a_node_until_time_is_up(self):
        for how in ("esc", "click"):
            game, state, node, bot = self.node_scene("HUNT")
            scene, before = game.scene, state.came_from
            trace, nodes = state.trace, state.stats["nodes"]
            # jacked in: ESC does nothing and the path offers no way back
            self.assertIsNone(self.crumb(game, "subnet1"))
            bot.key(pygame.K_ESCAPE)
            game.frame(0.02)
            self.assertIs(game.scene, scene)
            self.assertEqual(scene.phase, "play")
            # once time is up the way out is open: ESC or the path jacks out
            self.overtime(game, 0.1)
            if how == "esc":
                bot.key(pygame.K_ESCAPE)
            else:
                bot.click(self.crumb(game, "subnet1"))
            game.frame(0.02)
            self.assertEqual(scene.result, "jacked out")
            trace = state.trace
            bot.key(pygame.K_SPACE)
            game.frame(0.02)
            self.assertIsInstance(game.scene, scenes.MapScene)
            self.assertIs(state.position, before)           # as if it had never been entered
            self.assertFalse(node.done)
            self.assertEqual((state.trace, state.stats["nodes"]), (trace, nodes - 1))
            self.assertIn(node, state.available())          # and it can be entered again
            game.scene.enter(node)
            self.assertEqual(state.stats["nodes"], nodes)

    def test_back_from_the_map_abandons_the_run_when_asked_twice(self):
        root = os.path.basename(scenes.HERE)
        for name in ("raw", root):
            game, state, node, bot = self.node_scene("HUNT")
            game.scene.back_out()
            game.frame(0.02)
            self.assertIsInstance(game.scene, scenes.MapScene)
            bot.click(self.crumb(game, name))
            game.frame(0.02)
            self.assertIsInstance(game.scene, scenes.MapScene)      # the first click only warns
            self.assertIsNone(state.over)
            bot.click(self.crumb(game, name))
            game.frame(0.02)
            game.frame(0.02)
            self.assertIsInstance(game.scene, scenes.GameOverScene)
            self.assertTrue(state.abandoned)
            self.assertEqual(game.scene.path.hits, [])              # nowhere to go back to from the report

    def test_back_from_foothold_and_shop(self):
        game, state, node, bot = self.node_scene("HUNT")
        game.scene.back_out()
        state.trace, nodes = 40, state.stats["nodes"]
        rest = runmod.Node(node.layer, node.slot, "FOOTHOLD", "10.9.9.9:22", 5)
        state.move_to(rest)
        game.push(scenes.FootholdScene(game, state, rest))
        bot.key(pygame.K_ESCAPE)                                    # leave without resting
        game.frame(0.02)
        self.assertIsInstance(game.scene, scenes.MapScene)
        self.assertEqual((state.trace, rest.done, state.stats["nodes"]), (40, False, nodes))
        state.move_to(rest)
        game.push(scenes.FootholdScene(game, state, rest))
        bot.click(self.crumb(game, "subnet1"))                      # the same, by the path
        game.frame(0.02)
        self.assertIsInstance(game.scene, scenes.MapScene)
        self.assertEqual((state.trace, rest.done), (40, False))
        game.push(scenes.ShopScene(game, state, 6))
        bot.click(self.crumb(game, "subnet1"))                      # leaving a shop is just leaving it
        game.frame(0.02)
        self.assertIsInstance(game.scene, scenes.MapScene)

    def test_the_shop_opens_when_an_ids_goes_down(self):
        game, state, node, bot = self.node_scene("IDS")
        self.assertNotIn("SHOP", {n.kind for n in state.subnet.nodes.values()})     # none on the way through
        game.scene._end("solved")
        bot.key(pygame.K_SPACE)
        game.frame(0.05)
        shop = game.scene
        self.assertIsInstance(shop, scenes.ShopScene)               # between this subnet and the next
        self.assertEqual((state.level, state.position), (2, None))
        self.assertIsNotNone(self.crumb(game, "subnet2"))
        bot.key(pygame.K_ESCAPE)
        game.frame(0.05)
        self.assertIsInstance(game.scene, scenes.MapScene)
        self.assertEqual(game.scene._subnet, state.subnet)
        # the last IDS ends the run: there is nothing left to shop for
        game, state, node, bot = self.node_scene("IDS")
        state.level = runmod.SUBNETS
        game.scene._end("solved")
        bot.key(pygame.K_SPACE)
        game.frame(0.05)
        game.frame(0.05)
        self.assertEqual(state.over, "won")
        self.assertIsInstance(game.scene, scenes.GameOverScene)

    def test_back_in_the_tutorial_and_the_manual(self):
        root = os.path.basename(scenes.HERE)
        game = main.Game(save_path=self.save_path, captures_dir=self.captures, seed=1)
        bot, title = autoplay.Bot(game), game.scene
        bot.char("2")
        game.frame(0.02)
        scene = game.scene
        self.assertIsNone(self.crumb(game, "tutorial"))             # already at its start
        for _ in range(40):
            if scene.i == 2:
                break
            bot.on_TutorialScene(scene)
            game.frame(0.2)
        self.assertEqual(scene.i, 2)
        bot.click(self.crumb(game, "tutorial"))                     # back to the first step
        game.frame(0.02)
        self.assertEqual((game.scene, scene.i, scene.solved), (scene, 0, False))
        bot.click(self.crumb(game, root))
        game.frame(0.02)
        self.assertIs(game.scene, title)
        bot.char("3")
        game.frame(0.02)
        self.assertIsInstance(game.scene, scenes.LogsScene)
        bot.click(self.crumb(game, root))
        game.frame(0.02)
        self.assertIs(game.scene, title)
        self.assertEqual(title.path.hits, [])                       # the title is the top

    def test_levels_are_found_when_the_path_is_cut_to_fit(self):
        line, surf = scenes.PathLine(), pygame.Surface((ui.BASE_W, ui.BASE_H))
        ui.set_view((ui.BASE_W, ui.BASE_H))
        root = os.path.basename(scenes.HERE)
        hit = []
        crumbs = [("protocol", lambda: hit.append("mode")), ("subnet4", lambda: hit.append("map")),
                  ("fe80:0000:0000:0000:1234:5678:9abc:def0:44321", None), ("ids", None)]
        line.draw(surf, lambda: hit.append("root"), crumbs)
        full = "/".join([scenes.HERE] + [name for name, _ in crumbs])
        self.assertGreater(len(full), line.WIDTH)                   # too long: the front goes
        shown = ui.fit_path(full, line.WIDTH)
        for rect, name, action in line.hits:
            col = (rect.x - line.X) // ui.cw()
            self.assertEqual(shown[col:col + len(name)], name)      # each link sits exactly on its name
        self.assertTrue({"protocol", "subnet4"} <= {name for _, name, _ in line.hits})
        for rect, name, _ in line.hits:
            line.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=rect.center, button=1))
        self.assertTrue({"mode", "map"} <= set(hit))
        self.assertFalse(line.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(600, 400), button=1)))

    def test_shop_buy_sell_and_slots(self):
        game = main.Game(save_path=self.save_path, captures_dir=self.captures, seed=4)
        state = runmod.RunState("RAW", sources.RandomSource(), 4)
        state.credits = 500
        scene = scenes.ShopScene(game, state, 4)
        game.push(scene)
        bot = autoplay.Bot(game)
        first = scene.stock[0]
        bot.char("1")
        game.frame(0.05)
        self.assertEqual(state.tools, [first])
        self.assertEqual(state.credits, 500 - tools.TOOLS[first].price)
        self.assertNotIn(first, scene.stock)
        tool_slots = next(i for i, a in enumerate(scene.actions) if a[0] == "slot")
        bot.click(scene.menu.item_rect(tool_slots).center)
        game.frame(0.05)
        self.assertEqual(state.tool_slots, tools.START_SLOTS + 1)
        sell = next(i for i, a in enumerate(scene.actions) if a == ("sell", first))
        bot.char(str(sell + 1))
        game.frame(0.05)
        self.assertEqual(state.tools, [])
        state.credits = 0
        scene._build()
        self.assertFalse(any(item.get("enabled", True) for item, a in zip(scene.menu.items, scene.actions)
                             if a[0] in ("buy", "slot")))
        bot.key(pygame.K_ESCAPE)
        game.frame(0.05)
        self.assertIsNot(game.scene, scene)

    def test_abandoning_a_run(self):
        game = main.Game(save_path=self.save_path, captures_dir=self.captures, seed=6)
        bot = autoplay.Bot(game, mode="RAW", pace=1)
        for _ in range(20):
            if isinstance(game.scene, scenes.MapScene):
                break
            bot.step()
            game.frame(0.05)
        self.assertIsInstance(game.scene, scenes.MapScene)
        bot.key(pygame.K_l, "l")
        game.frame(0.05)
        self.assertIsInstance(game.scene, scenes.LogsScene)
        bot.key(pygame.K_ESCAPE)
        game.frame(0.05)
        bot.key(pygame.K_ESCAPE)
        game.frame(0.05)
        self.assertIsInstance(game.scene, scenes.MapScene)      # one ESC only warns
        bot.key(pygame.K_ESCAPE)
        game.frame(0.05)
        game.frame(0.05)
        self.assertIsInstance(game.scene, scenes.GameOverScene)
        self.assertTrue(game.run_state.abandoned)
        self.assertEqual(self.saved()["runs"], 1)

    def test_random_input_never_crashes(self):
        """Mash the mouse and keyboard at every scene for a few thousand frames."""
        keys = [pygame.K_SPACE, pygame.K_RETURN, pygame.K_ESCAPE, pygame.K_BACKSPACE, pygame.K_UP,
                pygame.K_DOWN, pygame.K_LEFT, pygame.K_RIGHT, pygame.K_PAGEDOWN, pygame.K_PAGEUP,
                pygame.K_TAB, pygame.K_F1, pygame.K_F3]
        rng, seen, game = random.Random(2024), set(), None
        for _ in range(8000):
            if game is None or not game.running or not game.stack:
                game = main.Game(save_path=self.save_path, captures_dir=self.captures, seed=rng.getrandbits(30))
                bot = autoplay.Bot(game)
            name = type(game.scene).__name__
            seen.add(name)
            pos = (rng.randrange(ui.W), rng.randrange(ui.H))
            if name == "PuzzleScene":
                scene = game.scene
                if rng.random() < 0.5:
                    hx = scene.hex
                    pos = (rng.randrange(hx.x, hx.x + hx.width), rng.randrange(hx.y, hx.y + hx.height))
                if scene.phase == "play" and rng.random() < 0.02:
                    for d in rng.sample(sorted(tools.TOOLS), 3):     # so tool paths get hit too
                        if scene.run.install(d):
                            scene.charges[d] = tools.TOOLS[d].uses
            r = rng.random()
            if name == "TitleScene" and r < 0.3:
                bot.char(rng.choice("12"))
            elif r < 0.25:
                bot.click(pos)
            elif r < 0.35:
                bot.move(pos)
            elif r < 0.42:
                bot.down(pos)
            elif r < 0.5:
                bot.up(pos)
            elif r < 0.55:
                bot.wheel(rng.choice([-3, -1, 1, 3]))
            elif r < 0.8:
                bot.char(rng.choice("0123456789abcdefqwrtym"))
            elif name != "TitleScene" or rng.random() < 0.1:
                key = rng.choice(keys)
                if key == pygame.K_ESCAPE and name == "MapScene" and rng.random() < 0.9:
                    key = pygame.K_SPACE
                bot.key(key)
            game.frame(rng.choice([0.016, 0.05, 0.5]))
            if game.run_state is not None:
                self.assertTrue(0 <= game.run_state.trace <= 100)
        self.assertTrue(MASHED_SCENES <= seen, seen)


class ViewTest(unittest.TestCase):
    """Layout units -> pixels: sharp at any scale, with nothing misaligned."""

    def tearDown(self):
        ui.set_view((ui.BASE_W, ui.BASE_H))

    def test_retina_window_and_fullscreen(self):
        ui.set_view((2560, 1600), (1280, 800))              # a window on a 2x display
        self.assertEqual((ui.SCALE, ui.W, ui.H), (2.0, 1280, 800))
        self.assertEqual(ui.to_layout((300, 200)), (300, 200))      # mouse events are in window coordinates
        self.assertEqual(ui.box((10, 20, 30, 40)), (20, 40, 60, 80))
        ui.set_view((3600, 2260), (1800, 1130))             # fullscreen on a 1800x1169 desktop: a little taller
        self.assertEqual((ui.SCALE, ui.W, ui.H), (2.8125, 1280, 803))
        self.assertEqual(ui.to_layout((900, 565)), (640, 402))
        for pos in ((0, 0), (1, 1), (637, 3), (1279, 802)):
            self.assertEqual(ui.to_layout(ui.to_window(pos)), pos)
        ui.set_view((2560, 1440))                           # fullscreen on a 16:9 display: wider
        self.assertEqual((ui.SCALE, ui.W, ui.H), (1.8, 1422, 800))
        ui.set_view((1024, 768))                            # smaller than the base grid and squarer: scaled down, taller
        self.assertEqual((ui.SCALE, ui.W, ui.H), (0.8, 1280, 960))

    def test_the_layout_reaches_every_corner(self):
        for pixels in ((1280, 800), (2560, 1440), (3600, 2260), (1024, 768), (700, 1300), (3440, 1440), (641, 977)):
            ui.set_view(pixels)
            self.assertTrue(ui.W >= ui.BASE_W and ui.H >= ui.BASE_H, pixels)
            self.assertTrue(ui.W == ui.BASE_W or ui.H == ui.BASE_H, pixels)     # it only grows one way
            self.assertEqual(ui.box((0, 0, 1, 1))[:2], (0, 0), pixels)      # no bars: the origin is the corner
            for edge, size in zip(ui.box((0, 0, ui.W, ui.H))[2:], pixels):
                self.assertTrue(size - ui.SCALE - 1 < edge <= size, (pixels, edge))     # to within a unit

    def test_text_is_rendered_at_the_pixel_size(self):
        for pixels in ((1280, 800), (2560, 1600), (3600, 2260), (1024, 768)):
            ui.set_view(pixels)
            for size in (14, 16, 18, 20):
                for s in ("0", "HEXBREACH", "0123456789abcdef" * 4, "TRACE " + ui.bar(0.4, 30), ui.BOX):
                    img = ui.render(s, "fg", size)
                    where = (pixels, size, s)
                    # exactly as wide as its cells, so text stays on the grid
                    self.assertEqual(img.get_width(), ui.box((0, 0, len(s) * ui.cw(size), 1))[2], where)
                    self.assertLessEqual(abs(img.get_height() - ui.lh(size) * ui.SCALE), 2, where)
                f, _ = ui._draw_font(size)
                self.assertLessEqual(f.size("0")[0], ui.cw(size) * ui.SCALE)
                self.assertGreater(f.size("0")[0], ui.cw(size) * ui.SCALE - 1.5)    # and not a small font spaced out

    def test_text_is_drawn_at_the_weight_macos_gives_it(self):
        """Heavier than the font's bare outlines, as a terminal shows it, and still on the grid."""
        weight = ui.WEIGHT
        self.assertTrue(any(weight))

        def fresh():
            for store in (ui._glyphs, ui._cache, ui._inks):
                store.clear()
            ui._cache_size = 0

        def restore():
            ui.WEIGHT = weight
            fresh()

        self.addCleanup(restore)

        def ink(size):
            fresh()
            img = ui.render("HEXBREACH 0123 netrunning", "fg", size)
            return img.get_size(), sum(img.get_at((x, y))[3] for x in range(img.get_width())
                                       for y in range(img.get_height()))

        for pixels in ((1280, 800), (2560, 1600), (3600, 2260)):
            ui.set_view(pixels)
            for size in (14, 16, 20):
                ui.WEIGHT = (0, 0)
                plain = ink(size)
                ui.WEIGHT = weight
                heavy = ink(size)
                where = (pixels, size)
                self.assertEqual(heavy[0], plain[0], where)                     # the same cells
                self.assertTrue(1.1 < heavy[1] / plain[1] < 1.6, (where, heavy[1] / plain[1]))   # more ink in them

    def test_capitals_are_all_one_height(self):
        if not os.path.exists(ui.FONT_FILES[0]):
            self.skipTest("the sizes that go wrong are Menlo's")
        self.assertFalse(ui._level(ui._file(32)))               # Menlo at 32px: B, E and F are a pixel taller
        for pixels in ((2560, 1440), (2560, 1600), (3024, 1964), (3600, 2260), (1920, 1080), (1700, 1000)):
            ui.set_view(pixels)
            for size in (14, 16, 18, 20):
                f, _ = ui._draw_font(size)
                tops = {top for _, _, _, top, _ in f.metrics(ui.CAPS)}      # the flat-topped ones: round ones overshoot
                self.assertEqual(len(tops), 1, (pixels, size))
        ui.set_view((2560, 1440))                               # fullscreen at 16:9: size 18 would have been 32px
        self.assertIsNot(ui._draw_font(18)[0], ui._file(32))

    def test_neighbouring_cells_meet(self):
        for pixels in ((2560, 1600), (3600, 2260), (1024, 768)):
            ui.set_view(pixels)
            for size in (14, 18):
                cw, lh = ui.cw(size), ui.lh(size)
                for n in range(60):
                    a, b = ui.box((24 + n * cw, 98, cw, lh)), ui.box((24 + (n + 1) * cw, 98, cw, lh))
                    self.assertEqual(a[0] + a[2], b[0])
                    a, b = ui.box((24, 98 + n * lh, cw, lh)), ui.box((24, 98 + (n + 1) * lh, cw, lh))
                    self.assertEqual(a[1] + a[3], b[1])
        # box-drawing lines are drawn to the cell edges, so they join across characters and rows
        for pixels in ((1280, 800), (2560, 1600), (3600, 2260), (1024, 768)):
            ui.set_view(pixels)
            img = ui.render(ui.BOX[10] * 3, "fg", 14)       # three horizontal lines in a row: one unbroken line
            wide, high = img.get_size()
            self.assertTrue(any(all(img.get_at((x, y))[3] for x in range(wide)) for y in range(high)), pixels)
            img = ui.render(ui.BOX[5], "fg", 14)            # a vertical line: runs the full height of its row
            wide, high = img.get_size()
            self.assertGreaterEqual(high, ui.box((0, 0, 1, ui.lh(14)))[3])
            self.assertTrue(any(all(img.get_at((x, y))[3] for y in range(high)) for x in range(wide)), pixels)


class CursorTest(unittest.TestCase):
    """The byte under the mouse gets a block cursor that blinks, as in a terminal."""

    def setUp(self):
        pygame.display.init()
        pygame.font.init()
        ui.set_view((ui.BASE_W, ui.BASE_H))
        self.surf = pygame.Surface((ui.BASE_W, ui.BASE_H))
        self.hx = hexview.HexView(24, 98, rows=4)
        self.hx.data = bytes(range(64))

    def at(self, idx, pane="hex"):
        self.surf.fill(ui.BLACK)
        self.hx.draw(self.surf)
        return tuple(self.surf.get_at(self.hx.byte_rect(idx, pane).topleft))[:3]

    def mouse(self, kind, idx):
        pos = self.hx.byte_rect(idx).center
        self.hx.handle_event(pygame.event.Event(kind, pos=pos, rel=(0, 0), buttons=(0, 0, 0), button=1))

    def test_blinks_in_both_panes(self):
        self.mouse(pygame.MOUSEMOTION, 5)
        self.assertEqual((self.at(5), self.at(5, "ascii")), (ui.TAN, ui.TAN))      # lit as soon as it moves
        self.assertEqual(self.at(6), ui.BLACK)
        self.hx._moved = time.monotonic() - ui.BLINK * 1.5                           # half a cycle later
        self.assertEqual((self.at(5), self.at(5, "ascii")), (ui.BLACK, ui.BLACK))
        self.hx._moved = time.monotonic() - ui.BLINK * 2.5
        self.assertEqual(self.at(5), ui.TAN)
        self.hx._moved = time.monotonic() - ui.BLINK * 1.5
        self.mouse(pygame.MOUSEMOTION, 9)                                            # moving relights it
        self.assertEqual((self.at(9), self.at(5)), (ui.TAN, ui.BLACK))

    def test_a_drag_selection_does_not_blink(self):
        self.hx.select_mode = "drag"
        self.mouse(pygame.MOUSEBUTTONDOWN, 5)
        self.mouse(pygame.MOUSEMOTION, 8)
        for phase in (0.5, 1.5, 2.5):
            self.hx._moved = time.monotonic() - ui.BLINK * phase
            self.assertEqual([self.at(i) for i in (5, 6, 7, 8, 9)], [ui.TAN] * 4 + [ui.BLACK])

    def test_menu_selection_blinks(self):
        menu = ui.Menu([{"label": "ONE"}, {"label": "TWO"}], 80, 100)
        corner = menu.item_rect(0).topleft

        def lit():
            self.surf.fill(ui.BLACK)
            menu.draw(self.surf)
            return tuple(self.surf.get_at(corner))[:3] == ui.TAN

        self.assertTrue(lit())
        menu._lit = (0, time.monotonic() - ui.BLINK * 1.5)
        self.assertFalse(lit())
        menu.index = 1                                      # the cursor moved off it
        self.assertFalse(lit())


if __name__ == "__main__":
    unittest.main()
