"""HEXBREACH: entry point, game loop, scene stack."""
import argparse
import os
import random

import startup

startup.step(20, "loading engine")      # for the starting-up popup: pygame is the slow import

import pygame  # noqa: E402

import puzzles  # noqa: E402
import run as runmod  # noqa: E402
import save as savemod  # noqa: E402
import scenes  # noqa: E402
import sources  # noqa: E402
import ui  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))

_window = None      # the one OS window, shared by every Game in the process (the tests make many)


class Game:
    def __init__(self, save_path=None, captures_dir=None, seed=None, fullscreen=None):
        # only what the game uses: initialising the audio mixer costs seconds
        # on macOS and there is no sound
        global _window
        startup.step(55, "opening display")
        pygame.display.init()
        pygame.font.init()
        self.save = savemod.Save(save_path)
        # A high-DPI window: on a Retina display its surface has twice the
        # pixels of its size, and ui draws at that density. It can be resized:
        # the layout fills it at any size or shape.
        if _window is None:
            startup.step(70, "opening window")
            _window = pygame.Window("HEXBREACH", (ui.BASE_W, ui.BASE_H), allow_high_dpi=True, resizable=True)
            _window.minimum_size = (ui.BASE_W // 2, ui.BASE_H // 2)
        self.window = _window
        self._view = None
        self._press = None          # a mouse press held back until it proves to be a click or a drag
        self._dragging = False
        self.marks = None           # (from, to, scene): text highlighted by dragging, as in a terminal
        if fullscreen is None:
            fullscreen = self.save.data["fullscreen"]
        if fullscreen:
            # macOS takes the starting-up popup off screen as the window slides
            # to fullscreen, and the slide itself shows the game is coming: the
            # popup fills its bar and goes now
            startup.done()
        self.set_fullscreen(fullscreen, remember=False)
        self.clock = pygame.time.Clock()
        self.captures_dir = captures_dir or os.environ.get("HEXBREACH_CAPTURES") or os.path.join(BASE, "captures")
        self.seed = seed            # fixed seed for reproducible runs; None = random
        self.running = True
        self.frames = 0
        self.run_state = None
        self.god = False            # god mode: switched on a run's screens, and stays as set for the next run
        startup.step(95, "drawing title")
        self.stack = [scenes.TitleScene(self)]

    # ---- scene stack
    @property
    def scene(self):
        return self.stack[-1]

    def push(self, scene):
        self.stack.append(scene)

    def pop(self):
        self.stack.pop()
        if self.stack:
            self.scene.resume()
        else:
            self.running = False

    def replace(self, scene):
        self.stack[-1] = scene

    def new_seed(self):
        return self.seed if self.seed is not None else random.SystemRandom().getrandbits(32)

    def start_run(self, mode, source):
        self.run_state = runmod.RunState(mode, source, self.new_seed(), self.save.unlocked())
        self.run_state.set_god(self.god)
        self.replace(scenes.ToolkitScene(self, self.run_state))

    def practice(self, kind, mode, level):
        """Jump straight into one puzzle (development / practice)."""
        source = sources.make_source(mode, self.captures_dir)
        state = runmod.RunState(mode, source, self.new_seed(), self.save.unlocked())
        state.set_god(self.god)
        state.level = max(1, min(runmod.SUBNETS, int(level)))
        cls = puzzles.REGISTRY.get(kind)
        if cls is not None and cls.own_levels:      # as far up its own levels as a run usually is by then
            state.solved[kind] = puzzles.step(level, cls.USUAL)
        node = runmod.Node(0, 0, kind, source.node_name(state.rng), state.rng.getrandbits(32))
        scene = scenes.PuzzleScene.open(self, state, node, level)
        self.push(scene)
        return scene

    # ---- display
    def set_fullscreen(self, on, remember=True):
        """Fullscreen fills the display at its own resolution; the layout is
        scaled up and fills it corner to corner."""
        if on:
            self.window.set_fullscreen(True)
        else:
            self.window.set_windowed()
        self.fullscreen = on
        if remember:
            self.save.data["fullscreen"] = on
            self.save.write()
        self._fit()

    def _surface(self):
        return self.window.get_surface()

    def _fit(self):
        """Point the view at the window's surface. Its size follows the
        window's, and a switch to or from fullscreen takes a moment to land."""
        self.screen = self._surface()
        view = (self.screen.get_size(), self.window.size)
        if view != self._view:
            self._view = view
            ui.set_view(*view)

    @staticmethod
    def _fullscreen_key(ev):
        """cmd+F (ctrl+cmd+F too), F11, or alt/cmd+ENTER."""
        if ev.key == pygame.K_F11:
            return True
        mod = getattr(ev, "mod", 0)
        return (ev.key == pygame.K_f and mod & pygame.KMOD_META) or (
            ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and mod & (pygame.KMOD_ALT | pygame.KMOD_META))

    # ---- highlighting text, as a terminal lets you
    DRAG = 4                    # units the mouse must travel with the button down to count as a drag

    def _mouse(self, ev):
        """Sort presses into clicks and drags. A press is held back until the
        button comes up: released where it went down, it was a click and the
        scene gets it; moved first, it was a drag, which highlights the text
        it crosses and clicks nothing. Scenes that use drags themselves (to
        select bytes) say so with owns_drag and get theirs at once.
        Yields the events the scene should see."""
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            self.marks = None
            self._dragging = False
            if self.scene.owns_drag(ev.pos):
                self._press = None
                yield ev
            else:
                self._press = ev
        elif ev.type == pygame.MOUSEMOTION and self._press is not None:
            a, b = self._press.pos, ev.pos
            if self._dragging or abs(a[0] - b[0]) + abs(a[1] - b[1]) > self.DRAG:
                self._dragging = True
                self.marks = (a, b, self.scene)
            yield ev
        elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1 and self._press is not None:
            press, self._press = self._press, None
            if self._dragging:
                self._dragging = False
                self.marks = (press.pos, ev.pos, self.scene)
            else:
                yield press
                yield ev
        else:
            yield ev

    def marked_text(self):
        """The highlighted text, or '' if nothing is."""
        return ui.marked_text(*self.marks[:2]) if self.marks else ""

    def copy_marked(self):
        """cmd+C: put the highlighted text on the clipboard. Returns it."""
        text = self.marked_text()
        if text:
            try:
                pygame.scrap.put_text(text)
            except (pygame.error, AttributeError):
                pass                # no clipboard here (a headless run): nothing to do
        return text

    # ---- loop
    def _key(self, ev):
        """Keys that work on every screen. True if the key was one of them."""
        mod = getattr(ev, "mod", 0)
        if self._fullscreen_key(ev):
            self.set_fullscreen(not self.fullscreen)
            return True
        if ev.key == pygame.K_c and mod & pygame.KMOD_META:
            self.copy_marked()
            return True
        if mod & (pygame.KMOD_META | pygame.KMOD_CTRL | pygame.KMOD_ALT) or not self.scene.menu_ok:
            return False
        if ev.key == pygame.K_m:
            self.push(scenes.MenuScene(self))
            return True
        if ev.key == pygame.K_l and not isinstance(self.scene, scenes.LogsScene):
            self.push(scenes.LogsScene(self))
            return True
        return False

    def frame(self, dt):
        self._fit()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                self.running = False
                return
            if not self.stack:
                return
            if ev.type == pygame.KEYDOWN and self._key(ev):
                continue
            if hasattr(ev, "pos") and ev.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEMOTION, pygame.MOUSEBUTTONUP):
                # scenes work in layout units, whatever the window's size
                ev = pygame.event.Event(ev.type, dict(ev.dict, pos=ui.to_layout(ev.pos)))
            for ev in self._mouse(ev):
                if not self.stack:
                    return
                scene = self.scene
                if scene.typing is not None and ev.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
                    if scene.skip_typing():     # any input: the rest of the screen appears at once
                        continue
                if scene.path.handle_event(ev):
                    continue                    # a click on the path line: gone back to that level
                if scenes.god_click(scene, ev):
                    continue                    # a click on the GOD MODE button: switched
                scene.handle_event(ev)
        if not self.stack:
            return
        scene = self.scene
        scene.update(dt)
        if self.scene is not scene:             # the update moved on to another screen: draw that one
            scene = self.scene
        if self.marks and self.marks[2] is not scene:
            self.marks = None                   # what was highlighted is no longer on screen
        if scene.typing is not None:
            scene.typing += dt
        # a screen that has just appeared types itself out
        ui.begin_frame()
        shown = None
        if scene.typing is not None:
            shown = int(scene.typing * max(scene.TYPE_CPS, scene.type_total / scene.TYPE_MAX))
        with ui.typewriter(shown) as typing:
            scene.draw(self.screen)
        scene.type_total = typing.total
        if typing.done:
            scene.typing = None
        if self.marks:
            ui.draw_marked(self.screen, *self.marks[:2])
        self.window.flip()

    def loop(self, bot=None, max_frames=None, fixed_dt=None):
        """Run until quit. fixed_dt skips the 60 fps clock (headless tests)."""
        while self.running and self.stack:
            dt = fixed_dt if fixed_dt is not None else min(self.clock.tick(60) / 1000.0, 0.1)
            if bot is not None:
                bot.step()
            self.frame(dt)
            startup.done()          # the first frame is up: the starting-up popup can go
            self.frames += 1
            if max_frames is not None and self.frames >= max_frames:
                break

    def screenshot(self, path):
        pygame.image.save(self.screen, path)


def main(argv=None):
    ap = argparse.ArgumentParser(description="HEXBREACH: a hex-dump netrunning roguelike")
    ap.add_argument("--seed", type=int, help="fixed seed for a reproducible run")
    ap.add_argument("--puzzle", choices=sorted(puzzles.REGISTRY) + ["IDS"],
                    help="practice: jump straight into one puzzle")
    ap.add_argument("--mode", choices=["RAW", "PROTOCOL", "LIVE"], default="PROTOCOL",
                    help="data mode for --puzzle / --autoplay")
    ap.add_argument("--level", type=float, default=1.0,
                    help="difficulty for --puzzle: 1 is the first node of a run, %d the last IDS; "
                         "2.5 is halfway through subnet 2" % (runmod.SUBNETS + 1))
    ap.add_argument("--autoplay", action="store_true", help="let the test bot play a whole run")
    ap.add_argument("--fullscreen", action="store_true", default=None, help="start in fullscreen")
    ap.add_argument("--windowed", dest="fullscreen", action="store_false", help="start in a window")
    args = ap.parse_args(argv)

    game = Game(seed=args.seed, fullscreen=args.fullscreen)
    bot = None
    if not 1 <= args.level <= runmod.SUBNETS + 1:
        ap.error("--level must be between 1 and %d" % (runmod.SUBNETS + 1))
    if args.puzzle:
        if args.mode not in puzzles.REGISTRY.get(args.puzzle, puzzles.Payload).modes:
            ap.error("%s is not available in %s mode" % (args.puzzle, args.mode))
        game.practice(args.puzzle, args.mode, args.level)
    if args.autoplay:
        from autoplay import Bot
        bot = Bot(game, mode=args.mode, pace=12)
    game.loop(bot=bot)
    pygame.quit()


if __name__ == "__main__":
    main()
