"""Visual check: play one node of each puzzle type in each data mode, in the
real window, and save screenshots for a human to look at.

    python tests/visual_check.py [output dir]        (default tests/shots)

Set SDL_VIDEODRIVER=dummy to render off-screen instead. Uses a throwaway save
and a generated capture, so it never touches save.json or captures/.
"""
import os
import random
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pygame  # noqa: E402

import autoplay  # noqa: E402
import main  # noqa: E402
import puzzles  # noqa: E402
import run as runmod  # noqa: E402
import scenes  # noqa: E402
import sources  # noqa: E402


def make_capture(directory):
    """A small synthetic capture so LIVE mode has something to read."""
    rng, syn, frames = random.Random(5), sources.SynthSource(), []
    for i in range(30):
        frames += syn.flow(rng, 1 + i % 5)
    sources.write_pcapng(os.path.join(directory, "sample.pcapng"), frames)


def spin(game, n=3):
    for _ in range(n):
        game.frame(1 / 60)


def play_node(game, bot, kind, mode, level, out, held=()):
    scene = game.practice(kind, mode, level)
    for d in held:
        scene.run.install(d)
    scene.charges.update({d: 1 for d in held})
    spin(game)
    tag = "%s_%s" % (mode.lower(), kind.lower())
    if kind == "IDS":
        game.screenshot(os.path.join(out, tag + "_0_brief.png"))
    bot.key(pygame.K_SPACE)
    spin(game)
    shot = False
    for _ in range(400):
        if scene.phase != "play":
            break
        p = scene.puzzle
        bot.on_PuzzleScene(scene)
        spin(game, 2)
        half = len(p.solution_actions()) // 2
        if not shot and len(bot._queue) <= half:
            # park the cursor on a byte to show the hex <-> ASCII hover link
            target = min(len(p.data) - 1, 0x16)
            bot.move(scene.hex.byte_rect(target, "ascii").center)
            spin(game)
            game.screenshot(os.path.join(out, tag + "_1_play.png"))
            shot = True
    assert scene.phase == "result" and scene.result == "solved", (mode, kind, scene.phase, scene.result)
    spin(game)
    game.screenshot(os.path.join(out, tag + "_2_solved.png"))
    bot.key(pygame.K_SPACE)
    spin(game)


def main_check(out):
    os.makedirs(out, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="hexbreach-visual-")
    make_capture(tmp)
    game = main.Game(save_path=os.path.join(tmp, "save.json"), captures_dir=tmp, seed=4242)
    bot = autoplay.Bot(game, pace=1)
    spin(game, 8)
    game.screenshot(os.path.join(out, "title_booting.png"))
    spin(game, 90)
    bot.move(game.scene.dump.byte_rect(0x1b).center)        # the title dump is live: cursor on a byte and its letter
    spin(game)
    game.screenshot(os.path.join(out, "title.png"))

    # the tutorial: each step as asked, after a wrong answer, and once solved
    bot.char("2")
    spin(game)
    scene = game.scene
    while game.scene is scene:
        tag = "tutorial_%d" % (scene.i + 1)
        if scene.want and scene.want[0] == "click":
            bot.move(scene.hex.byte_rect(scene.want[1] + 3).center)
        spin(game)
        game.screenshot(os.path.join(out, tag + "_0_task.png"))
        if scene.i == 0:
            for n in (17, 18):
                bot.click(scene.hex.byte_rect(scene.want[1] + n).center)
                spin(game)
            game.screenshot(os.path.join(out, tag + "_1_miss.png"))
        if scene.want:
            bot.on_TutorialScene(scene)
            spin(game)
            game.screenshot(os.path.join(out, tag + "_2_done.png"))
        spin(game, 30)
        bot.key(pygame.K_SPACE)
        spin(game)
    game.screenshot(os.path.join(out, "title_after_tutorial.png"))

    for mode in ("RAW", "PROTOCOL", "LIVE"):
        for n, kind in enumerate(puzzles.kinds_for_mode(mode)):
            held = ("DISSECTOR", "BRUTEFORCE") if mode == "PROTOCOL" else ()
            play_node(game, bot, kind, mode, 1 + n % 3, out, held)
        play_node(game, bot, "IDS", mode, 3, out)

    # the other screens
    game.push(scenes.LogsScene(game))
    spin(game)
    game.screenshot(os.path.join(out, "manual_ethernet.png"))
    for name, presses in (("ipv4", 1), ("tcp", 2), ("files", 4)):
        for _ in range(presses):
            bot.key(pygame.K_RIGHT)
        spin(game)
        game.screenshot(os.path.join(out, "manual_%s.png" % name))
    game.pop()
    game.push(scenes.ModeScene(game))
    spin(game)
    game.screenshot(os.path.join(out, "mode_select.png"))
    bot.char("2")
    spin(game)
    game.screenshot(os.path.join(out, "loadout.png"))
    bot.char("1")
    spin(game)
    state = game.run_state
    game.screenshot(os.path.join(out, "map_start.png"))
    # walk a few hops so the map shows a position, a path and live edges
    for _ in range(3):
        node = state.available()[0]
        state.move_to(node)
        state.complete(node)
    state.trace, state.credits = 62, 180
    state.install("SNAPSHOT")
    node = state.available()[0]
    bot.move(game.scene.node_rects[node.id].center)
    spin(game)
    game.screenshot(os.path.join(out, "map_midway.png"))
    game.push(scenes.ShopScene(game, state, 77))
    spin(game)
    game.screenshot(os.path.join(out, "shop.png"))
    game.pop()
    state.trace = 100
    state.over = "traced"
    spin(game, 30)
    game.screenshot(os.path.join(out, "game_over_typing.png"))
    spin(game, 150)
    game.screenshot(os.path.join(out, "game_over.png"))
    pygame.quit()
    print("screenshots written to", out)


if __name__ == "__main__":
    main_check(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "tests", "shots"))
