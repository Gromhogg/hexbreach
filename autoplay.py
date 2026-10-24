"""A bot that plays HEXBREACH through real pygame events (mouse moves, clicks,
drags, wheel, key presses). Used by the headless smoke test and by
`python main.py --autoplay`. It reads each puzzle's known solution, but
everything it does goes through the same input path a player uses."""
import random

import pygame

import ui


class Bot:
    def __init__(self, game, mode="PROTOCOL", pace=2, solve=True, wrong=0.0, seed=0, on_frame=None):
        self.game = game
        self.mode = mode
        self.pace = pace            # frames between actions
        self.solve = solve          # False: sit in every puzzle until it times out
        self.wrong = wrong          # chance of one deliberate mistake per puzzle
        self.rng = random.Random(seed)
        self.on_frame = on_frame    # optional callback(bot, scene) every step
        self.tick = 0
        self.outcome = None         # "won" / "traced" once a run has ended
        self.finished = False
        self.seen = set()           # scene class names visited
        self.kinds = set()          # puzzle kinds played
        self._puzzle = None
        self._queue = []
        self._shopped = None

    # ---- event helpers
    @staticmethod
    def post(kind, **attrs):
        pygame.event.post(pygame.event.Event(kind, **attrs))

    def key(self, key, uni=""):
        self.post(pygame.KEYDOWN, key=key, unicode=uni, mod=0, scancode=0)
        self.post(pygame.KEYUP, key=key, unicode=uni, mod=0, scancode=0)

    def char(self, ch):
        self.key(ord(ch), ch)

    # positions are in layout units; a real mouse reports window coordinates
    def move(self, pos):
        self.post(pygame.MOUSEMOTION, pos=ui.to_window(pos), rel=(0, 0), buttons=(0, 0, 0))

    def down(self, pos):
        self.post(pygame.MOUSEBUTTONDOWN, pos=ui.to_window(pos), button=1)

    def up(self, pos):
        self.post(pygame.MOUSEBUTTONUP, pos=ui.to_window(pos), button=1)

    def click(self, pos):
        self.move(pos)
        self.down(pos)
        self.up(pos)

    def wheel(self, y):
        self.post(pygame.MOUSEWHEEL, x=0, y=y, flipped=False)

    # ---- driver
    def step(self):
        self.tick += 1
        scene = self.game.scene
        if self.on_frame is not None:
            self.on_frame(self, scene)
        if self.tick % self.pace:
            return
        name = type(scene).__name__
        self.seen.add(name)
        getattr(self, "on_" + name)(scene)

    def on_TitleScene(self, scene):
        if self.outcome is not None:
            self.finished = True
            self.game.running = False
        else:
            self.char("1")

    def on_TutorialScene(self, scene):
        if scene.solved:
            return self.key(pygame.K_SPACE)
        hx, want = scene.hex, scene.want
        if want[0] == "click":
            self.click(hx.byte_rect(want[1], "ascii" if self.rng.random() < 0.5 else "hex").center)
        elif want[0] == "select":
            start, end = hx.byte_rect(want[1]).center, hx.byte_rect(want[2]).center
            self.move(start)
            self.down(start)
            self.move(end)
            self.up(end)
        else:
            for ch in want[1]:
                self.char(ch)

    def on_ModeScene(self, scene):
        self.char(str(["RAW", "PROTOCOL", "LIVE"].index(self.mode) + 1))

    def on_ToolkitScene(self, scene):
        self.click(scene.menu.item_rect(0).center)

    def on_MapScene(self, scene):
        avail = scene.run.available()
        if not avail or not scene.node_rects:
            return
        fresh = [n for n in avail if n.kind not in self.kinds]     # a kind not played yet, when there is one
        node = self.rng.choice(fresh or avail)
        self.click(scene.node_rects[node.id].center)

    def on_ShopScene(self, scene):
        if self._shopped is not scene:
            self._shopped = scene
            if scene.menu.items[0].get("enabled", True):
                return self.char("1")
        self.key(pygame.K_ESCAPE)

    def on_FootholdScene(self, scene):
        self.char("1" if scene.run.trace >= 25 else "2")

    def on_LogsScene(self, scene):
        self.key(pygame.K_ESCAPE)

    def on_GameOverScene(self, scene):
        self.outcome = scene.run.over
        self.key(pygame.K_SPACE)

    def on_PuzzleScene(self, scene):
        if scene.phase != "play":
            return self.key(pygame.K_SPACE)
        if not self.solve:
            return
        p = scene.puzzle
        if self._puzzle is not p:
            self._puzzle = p
            self.kinds.add(p.kind)
            self._queue = list(p.solution_actions())
            if self.rng.random() < self.wrong:
                self._queue[:0] = self.blunder(p)
        if not self._queue:
            return
        hx, act = scene.hex, self._queue[0]
        if act[0] == "move":
            if not (hx.is_visible(act[1]) and hx.is_visible(act[2])):
                return self.wheel(1 if act[2] // hx.cols < hx.scroll else -1)
            start, end = hx.byte_rect(act[1]).center, hx.byte_rect(act[2]).center
            self.move(start)
            self.down(start)
            self.move(end)
            self.up(end)
        elif act[0] in ("click", "select"):
            idx = act[1]
            if not hx.is_visible(idx) or (act[0] == "select" and not hx.is_visible(act[2])):
                return self.wheel(1 if idx // hx.cols < hx.scroll else -1)
            pane = "hex" if hx.hide_ascii or self.rng.random() < 0.7 else "ascii"
            start = hx.byte_rect(idx, pane).center
            if act[0] == "click":
                self.click(start)
            else:
                end = hx.byte_rect(act[2], pane).center
                self.move(start)
                self.down(start)
                self.move(end)
                self.up(end)
        elif act[0] == "type":
            for ch in act[1]:
                self.char(ch)
        elif act[0] == "key":
            if act[1] == "enter":
                self.key(pygame.K_RETURN, "\r")
            else:
                self.char(act[1])
        self._queue.pop(0)

    @staticmethod
    def blunder(p):
        """One deliberately wrong input for a puzzle (none exists for PAYLOAD,
        where an illegal pick is simply refused)."""
        if p.kind == "HUNT":
            taken = {s + j for s in p.solution for j in range(len(p.pattern))}
            return [("click", next(i for i in range(len(p.data)) if i not in taken))]
        if p.kind == "CARVE":
            return [("click", next(i for i in range(len(p.data)) if p.data[i:i + 1] and not any(
                pos <= i < pos + 24 for pos, _ in p.files) and not any(lo <= i < hi for lo, hi in p.decoys)))]
        if p.kind == "DISSECT":
            lo, hi = p.solution[0]
            return [("select", lo, hi + 1)] if hi + 1 < len(p.data) else []
        if p.kind == "XOR" and not p.found:      # the pattern is still to find: a click well away from it
            return [("click", (p.hint_off + len(p.data) // 2) % len(p.data))]
        if p.kind == "XOR":
            return [("type", p.typing(bytes(p.keylen))), ("key", "enter")]
        if p.kind == "REASSEMBLE":      # a segment dropped one byte past where it goes
            start, off = p.solution[0]
            return [("move", start, off + 1)] if off + 1 < p.length else []
        if p.kind == "CHECKSUM":
            off, good = p.solution
            bad = next(v for v in range(256) if v != p.data[off] and not p.validate((off, v)))
            return [("click", off), ("type", "%02x" % bad)]
        if p.kind == "IDS":
            # ALERT LOG: clear an armed entry that is not about you (another IDS game would branch on type(p))
            e = next((e for e in range(p.count) if e not in p.targets and p.data[p.offset(e, "alert")] == 1), None)
            return [("click", p.offset(e, "alert")), ("type", "00")] if e is not None else []
        return []
