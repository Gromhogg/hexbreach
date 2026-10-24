"""God mode, headless: the button in the bottom right of a run's screens, and
what it changes. Credits never run out, TRACE never rises, any node or subnet
can be gone to, and nothing is solved for you."""
import json
import os
import sys
import tempfile
import unittest

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

import autoplay  # noqa: E402
import main  # noqa: E402
import run as runmod  # noqa: E402
import scenes  # noqa: E402
import sources  # noqa: E402
import tools  # noqa: E402
import ui  # noqa: E402


class GodModeTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="hexbreach-god-")
        self.save_path = os.path.join(self.dir, "save.json")
        self.captures = os.path.join(self.dir, "captures")
        os.mkdir(self.captures)

    def on_the_map(self, seed=11):
        """A run on its map, drawn once so the button is there to click."""
        game = main.Game(save_path=self.save_path, captures_dir=self.captures, seed=seed)
        state = runmod.RunState("RAW", sources.RandomSource(), seed)
        game.run_state = state
        game.push(scenes.MapScene(game, state))
        bot = autoplay.Bot(game)
        self.frames(game)
        return game, state, bot

    @staticmethod
    def frames(game, n=3, dt=0.02):
        for _ in range(n):
            game.frame(dt)

    def switch(self, game, bot):
        bot.click(game.scene.god_rect.center)
        self.frames(game)

    def shown(self):
        return [s for _, _, s, _ in ui.runs]

    def test_the_button_is_in_the_bottom_right_and_switches(self):
        game, state, bot = self.on_the_map()
        rect = game.scene.god_rect
        self.assertEqual((rect.right, rect.bottom), (ui.W - 24, ui.H - 10))     # the bottom right corner
        self.assertIn(scenes.GOD_LABEL, self.shown())
        self.assertIn("CREDITS %d" % runmod.START_CREDITS, self.shown())
        self.assertFalse(state.god or state.god_used or game.god)
        self.switch(game, bot)
        self.assertTrue(state.god and state.god_used and game.god)
        self.assertIn("CREDITS ∞", self.shown())
        self.assertIsInstance(game.scene, scenes.MapScene)                      # the click did nothing else
        self.assertEqual(state.position, None)
        self.switch(game, bot)
        self.assertFalse(state.god or game.god)
        self.assertTrue(state.god_used)                                         # it was on: that is not forgotten
        self.assertIn("CREDITS %d" % runmod.START_CREDITS, self.shown())
        # nothing on the top line runs into anything else, even with a long path and a lot of credits
        state.credits = 99999
        self.frames(game)
        top = sorted((x, x + len(s) * ui.cw(size)) for x, y, s, size in ui.runs if y == 10)
        self.assertEqual(len(top), 2)                                           # the path, the credits
        for (_, end), (start, _) in zip(top, top[1:]):
            self.assertLess(end, start)
        self.assertLessEqual(scenes.PathLine.X + scenes.PathLine.WIDTH * ui.cw(), top[1][0])

    def test_nothing_runs_into_the_button(self):
        game, state, bot = self.on_the_map()
        state.tool_slots = tools.MAX_SLOTS
        # the tools with the most to say: the map writes each one's description, down the right side
        state.tools = sorted(tools.TOOLS, key=lambda d: -len(tools.TOOLS[d].desc))[:tools.MAX_SLOTS]
        self.frames(game)
        self.assertNothingOnTheButton(game)
        node = state.available()[0]
        state.move_to(node)
        game.push(scenes.PuzzleScene.open(game, state, node, 1, brief=False))
        self.frames(game)
        self.assertNothingOnTheButton(game)

    def assertNothingOnTheButton(self, game):
        button = game.scene.god_rect
        for x, y, s, size in ui.runs:
            if s != scenes.GOD_LABEL:
                rect = pygame.Rect(x, y, len(s) * ui.cw(size), ui.lh(size))
                self.assertFalse(rect.colliderect(button), s)

    def test_trace_never_rises(self):
        game, state, bot = self.on_the_map()
        self.switch(game, bot)
        state.trace = 40.0
        for _ in range(200):
            state.tick(1.0)                                 # the clock
        state.add_trace(500)                                # anything else
        self.assertEqual((state.trace, state.over), (40.0, None))
        state.add_trace(-15)                                # it can still fall
        self.assertEqual(state.trace, 25.0)
        # inside a node: mistakes and overtime cost nothing, and the run goes on
        node = state.subnet.layer(0)[0]
        game.scene.enter(node)
        scene = game.scene
        self.assertIsInstance(scene, scenes.PuzzleScene)
        scene._handle("mistake")
        self.assertEqual((scene.mistakes, scene.last_cost, state.trace), (1, 0, 25.0))
        scene.left = 0.01
        for _ in range(400):
            game.frame(0.05)
        self.assertTrue(scene.overtime)
        self.assertEqual((state.trace, state.over, scene.overtime_trace), (25.0, None, 0.0))
        self.assertIs(game.scene, scene)
        # switched off, TRACE rises again from where it was
        self.switch(game, bot)
        self.assertFalse(state.god)
        game.frame(1.0)
        self.assertGreater(state.trace, 25.0)

    def test_credits_never_run_out(self):
        game, state, bot = self.on_the_map()
        state.credits = 0
        scene = scenes.ShopScene(game, state, 4)
        game.push(scene)
        self.frames(game)
        buys = [i for i, a in enumerate(scene.actions) if a[0] in ("buy", "slot")]
        self.assertFalse(any(scene.menu.items[i].get("enabled", True) for i in buys))
        self.switch(game, bot)                              # the button is on the market's screen too
        self.assertTrue(state.god)
        self.assertIs(game.scene, scene)
        buys = [i for i, a in enumerate(scene.actions) if a[0] in ("buy", "slot")]
        self.assertTrue(all(scene.menu.items[i].get("enabled", True) for i in buys))
        first = scene.stock[0]
        bot.click(scene.menu.item_rect(0).center)
        self.frames(game)
        self.assertEqual((state.tools, state.credits), ([first], 0))        # bought, and nothing taken
        slot = next(i for i, a in enumerate(scene.actions) if a[0] == "slot")
        bot.click(scene.menu.item_rect(slot).center)
        self.frames(game)
        self.assertEqual((state.tool_slots, state.credits), (tools.START_SLOTS + 1, 0))
        self.switch(game, bot)                              # off again: nothing can be afforded
        buys = [i for i, a in enumerate(scene.actions) if a[0] in ("buy", "slot")]
        self.assertTrue(buys)
        self.assertFalse(any(scene.menu.items[i].get("enabled", True) for i in buys))

    def test_any_node_can_be_gone_to_and_none_is_solved_for_you(self):
        game, state, bot = self.on_the_map()
        board = game.scene
        far = next(n for n in state.subnet.layer(3) if n.kind != "FOOTHOLD")
        self.assertNotIn(far, state.available())
        bot.click(board.node_rects[far.id].center)          # god mode off: only the next nodes can be clicked
        self.frames(game)
        self.assertIs(game.scene, board)
        self.assertEqual(state.position, None)
        self.switch(game, bot)
        bot.click(board.node_rects[far.id].center)
        self.frames(game)
        scene = game.scene
        self.assertIsInstance(scene, scenes.PuzzleScene)
        self.assertIs(scene.node, far)
        self.assertEqual(scene.phase, "play")               # in it, with the puzzle still to do
        self.assertIs(state.position, far)
        self.assertFalse(any(n.done for n in state.subnet.nodes.values()))
        self.assertEqual((state.stats["solved"], state.credits), (0, runmod.START_CREDITS))
        # solve it for real: only that node is done, and the map carries on from there
        scene._end("solved")
        bot.key(pygame.K_SPACE)
        self.frames(game)
        self.assertIs(game.scene, board)
        self.assertEqual([n for n in state.subnet.nodes.values() if n.done], [far])
        self.assertEqual(state.available(), [state.subnet.nodes[i] for i in far.next])
        # the IDS too, straight from here
        boss = state.subnet.boss
        bot.click(board.node_rects[boss.id].center)
        self.frames(game)
        self.assertIs(game.scene.node, boss)
        self.assertTrue(game.scene.is_boss)
        self.assertEqual((state.level, boss.done, state.stats["ids"]), (1, False, 0))
        for _ in range(20):
            game.frame(0.05)                                # the map behind draws a path with gaps in it: no crash

    def test_any_subnet_can_be_gone_to(self):
        game, state, bot = self.on_the_map()
        board = game.scene
        self.assertEqual(board._jumps, [])                  # no subnet numbers without god mode
        self.switch(game, bot)
        self.assertEqual([level for _, level in board._jumps], list(range(1, runmod.SUBNETS + 1)))
        self.assertTrue(all(rect.y == 34 and rect.right <= ui.W - 24 for rect, _ in board._jumps))
        first = state.subnet
        node = first.layer(0)[0]
        state.move_to(node)
        state.complete(node)
        bot.click(board._jumps[3][0].center)                # subnet 4
        self.frames(game)
        self.assertEqual((state.level, state.subnet.level), (4, 4))
        self.assertIsNot(state.subnet, first)
        self.assertIs(game.scene, board)
        self.assertEqual(state.position, None)
        self.assertFalse(any(n.done for n in state.subnet.nodes.values()))
        self.assertEqual((state.stats["ids"], state.stats["solved"], state.over), (0, 0, None))
        self.assertEqual(set(board.node_rects), set(state.subnet.nodes))
        # a node there is as hard as subnet 4's
        far = next(n for n in state.subnet.layer(2) if n.kind != "FOOTHOLD")
        bot.click(board.node_rects[far.id].center)
        self.frames(game)
        self.assertEqual(game.scene.level, state.node_level(far))
        self.assertGreaterEqual(game.scene.level, 4)
        game.scene._end("jacked out")
        bot.key(pygame.K_SPACE)
        self.frames(game)
        self.assertIs(game.scene, board)
        # back to the subnet that was left: it is as it was
        bot.click(board._jumps[0][0].center)
        self.frames(game)
        self.assertIs(state.subnet, first)
        self.assertEqual((state.level, state.position), (1, node))
        self.assertTrue(node.done)
        bot.click(board._jumps[0][0].center)                # the one you are in: nothing happens
        self.frames(game)
        self.assertIs(state.subnet, first)
        # the last subnet's IDS still wins the run
        bot.click(board._jumps[-1][0].center)
        self.frames(game)
        self.assertEqual(state.level, runmod.SUBNETS)
        state.complete(state.subnet.boss)
        self.assertEqual(state.over, "won")

    def test_a_god_mode_run_stays_out_of_the_records(self):
        game, state, bot = self.on_the_map()
        self.switch(game, bot)
        self.switch(game, bot)                              # off again: it still was on in this run
        state.level = runmod.SUBNETS
        state.over = "won"
        self.frames(game)
        self.assertIsInstance(game.scene, scenes.GameOverScene)
        for _ in range(200):
            game.frame(0.05)
            if game.scene.typing is None:
                break
        self.assertTrue(any(s.startswith("god mode") for s in self.shown()), self.shown())
        with open(self.save_path) as fh:
            data = json.load(fh)
        self.assertEqual((data["runs"], data["wins"], data["deepest_subnet"], data["best_run"]), (0, 0, 0, {}))

    def test_it_stays_as_set_for_the_next_run(self):
        game, state, bot = self.on_the_map()
        self.switch(game, bot)
        game.start_run("RAW", sources.RandomSource())
        self.assertTrue(game.run_state.god and game.run_state.god_used)
        self.assertTrue(game.practice("HUNT", "RAW", 1).run.god)
        game.god = False
        game.start_run("RAW", sources.RandomSource())
        self.assertFalse(game.run_state.god or game.run_state.god_used)

    def test_how_it_works_is_in_the_manual_and_the_page_fits(self):
        game, state, bot = self.on_the_map()
        self.switch(game, bot)
        shown = " ".join(self.shown())
        self.assertNotIn("click any node", shown)           # no instructions on the screen itself
        keys = [k for k, does in scenes.KEYBINDS]
        self.assertIn("GOD MODE", keys)
        for words in ("click [GOD MODE]", "click any node on the map", "click a SUBNET number"):
            self.assertIn(words, keys)
        bot.char("m")
        self.frames(game)
        menu = game.scene
        self.assertIsInstance(menu, scenes.MenuScene)
        bot.char("1")                                       # KEYS
        for _ in range(60):
            game.frame(0.05)
        self.assertEqual(menu.page, "keys")
        rows = [(x, y, s) for x, y, s, _ in ui.runs if "go straight to" in s]
        self.assertEqual(len(rows), 2)
        foot = menu.Y + menu.H - 2 * ui.lh()
        for x, y, s in rows:
            self.assertLess(y + ui.lh(), foot)                              # above the foot of the popover
            self.assertLess(x + len(s) * ui.cw(), menu.X + menu.W)          # and inside its frame
        self.assertGreaterEqual(menu.Y, 0)
        self.assertLessEqual(menu.Y + menu.H, ui.BASE_H)


if __name__ == "__main__":
    unittest.main()
