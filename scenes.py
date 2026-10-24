"""Scenes: title, tutorial, mode select, loadout, map, puzzle, shop, rest,
field manual, game over. Each has handle_event / update / draw; main.py keeps
them on a stack."""
import math
import os
import random
import time

import pygame

import tools
import glossary
import packets
import puzzles
import run as runmod
import sources
import ui
from hexview import STYLES, HexView
from puzzles.ids import MODIFIERS
from puzzles.carve import SIGNATURES

CONFIRM = (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE)
HERE = os.path.dirname(os.path.abspath(__file__))       # the game's own directory: the root of the path line


class PathLine:
    """The top line of every screen: where you are, the way pwd would print
    it. It starts at the game's real directory and grows as you go deeper.
    A level that has something to go back to can be clicked."""
    X, Y, WIDTH = 24, 10, 98        # WIDTH in characters: the rest of the line is the credits

    def __init__(self):
        self.hits = []              # (rect, name, action) of the levels that can be clicked, as last drawn
        self.mouse = (-1, -1)
        self.lit = (None, 0.0)      # (name under the mouse, since when): the hover blinks like any cursor

    def handle_event(self, ev):
        """True if the event was a click on a level, which has then been acted on."""
        if ev.type == pygame.MOUSEMOTION:
            self.mouse = ev.pos
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            for rect, _, action in self.hits:
                if rect.collidepoint(ev.pos):
                    action()
                    return True
        return False

    def draw(self, surf, root, crumbs):
        """root: what clicking the game's directory does (None: nothing).
        crumbs: (name, action or None) for each level below it."""
        names = [os.path.basename(HERE)] + [name for name, _ in crumbs]
        actions = [root] + [action for _, action in crumbs]
        shown = ui.fit_path("/".join([os.path.dirname(HERE)] + names), self.WIDTH)
        ui.text(surf, shown, self.X, self.Y, "dim")
        # find each level in the line as shown, working back from the end (the front may have been cut)
        self.hits, end, cw = [], len(shown), ui.cw()
        for name, action in zip(reversed(names), reversed(actions)):
            start = end - len(name)
            if start < 0 or shown[start:end] != name:
                break
            if action is not None:
                self.hits.append((pygame.Rect(self.X + start * cw, self.Y, len(name) * cw, ui.lh()), name, action))
            end = start - 1
        over = next(((rect, name) for rect, name, _ in self.hits if rect.collidepoint(self.mouse)), None)
        if over is None:
            self.lit = (None, 0.0)
            return
        rect, name = over
        if self.lit[0] != name:
            self.lit = (name, time.monotonic())
        if ui.blink(self.lit[1]):
            ui.text(surf, name, rect.x, rect.y, "bg", bg="tan")
        else:
            ui.text(surf, name, rect.x, rect.y, "tan")


class Scene:
    # A screen that has just appeared types itself out at TYPE_CPS characters a
    # second, or faster if it has so much on it that it would take over TYPE_MAX seconds.
    TYPE_CPS = 1500
    TYPE_MAX = 0.8
    menu_ok = True              # M (the menu) and L (the logs) work here

    def __init__(self, game):
        self.game = game
        self.path = PathLine()
        self.typing = 0.0       # seconds spent typing itself out so far; None once it is all there
        self.type_total = 0     # characters on the screen, as counted the last time it was drawn
        self.god_rect = None    # where the GOD MODE button was last drawn: only a run's screens have one

    def skip_typing(self):
        """A key or click arrived while the screen was still typing: show the
        rest at once. Return True to swallow that input."""
        self.typing = None
        return False

    def owns_drag(self, pos):
        """True if a mouse drag starting here is the scene's own (selecting
        bytes) rather than the player highlighting text."""
        return False

    def handle_event(self, ev):
        pass

    def update(self, dt):
        pass

    def draw(self, surf):
        pass

    def resume(self):
        """Called when the scene above this one is popped."""

    # ---- the path line
    def crumbs(self):
        """The levels of the path below the game's directory, as (name, action):
        the action goes back to that level, or is None if there is no going back."""
        return []

    def root(self):
        """What clicking the game's own directory in the path does. None: nothing."""
        return None

    def draw_path(self, surf):
        self.path.draw(surf, self.root(), self.crumbs())


def is_press(ev):
    """A key or click that means 'go on'."""
    return (ev.type == pygame.KEYDOWN and (ev.key in CONFIRM or ev.key == pygame.K_ESCAPE)) or (
        ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1)


def run_crumbs(run, leave_run=None, to_map=None, *deeper):
    """Path levels for a screen inside a run: mode, subnet, then any names
    deeper than the map. leave_run and to_map are what clicking the first two does."""
    return [(run.mode.lower(), leave_run), ("subnet%d" % min(run.level, runmod.SUBNETS), to_map)] + [
        (name, None) for name in deeper]


GOD_LABEL = "[GOD MODE]"


def draw_header(scene, surf, run):
    """Credits, the TRACE bar and the clock's rate at the top, and the GOD MODE
    button in the bottom right: on every screen of a run."""
    scene.draw_path(surf)
    ui.text_right(surf, "CREDITS %s" % ("\u221e" if run.god else run.credits), ui.W - 24, 10, "amber")
    x = ui.text(surf, "TRACE %s %3d%%" % (ui.bar(run.trace / 100, 30), run.trace), 24, 34,
                ui.trace_color(run.trace))
    rate = "does not rise in god mode" if run.god else "+%d%% / %ds" % (runmod.CLOCK_TRACE, run.clock_tick())
    ui.text(surf, rate, x + 3 * ui.cw(), 34, "dim")
    # the button, in the bottom right corner: lit while god mode is on
    x, y = ui.W - 24 - len(GOD_LABEL) * ui.cw(), ui.H - 10 - ui.lh()
    scene.god_rect = pygame.Rect(x, y, len(GOD_LABEL) * ui.cw(), ui.lh())
    over = scene.god_rect.collidepoint(scene.path.mouse)
    if run.god:
        ui.text(surf, GOD_LABEL, x, y, "bg", bg="tan" if over else "amber")
    else:
        ui.text(surf, GOD_LABEL, x, y, "tan" if over else "dim")


def god_click(scene, ev):
    """True if the event was a click on the GOD MODE button, which has then
    been switched. The setting is the game's: it stays as set for the next run."""
    rect = scene.god_rect
    if (rect is None or ev.type != pygame.MOUSEBUTTONDOWN or ev.button != 1
            or not rect.collidepoint(ev.pos)):
        return False
    game, run = scene.game, scene.run
    game.god = not run.god
    run.set_god(game.god)
    run.note("GOD MODE %s" % ("ON" if game.god else "OFF"), "tan")
    return True


NOTE_SIZE = 14      # the smaller text a tool's description is written in


def draw_tools(surf, run, x, y, charges=None, keys=True, desc=0):
    """Held tools. Returns {tool id: rect} for clicking. keys: they can be
    used here, so an active one shows its key and is lit while it has uses left.
    desc: write each tool's description under its name, this many characters across."""
    rects = {}
    head = "TOOLS %d/%d" % (len(run.tools), run.tool_slots)
    if tools.footprint(run.tools):
        head += "  footprint +%d%%" % round(100 * tools.footprint(run.tools))
    ui.text(surf, head, x, y, "dim")
    line, pad = ui.lh(), "    " if keys else ""
    below = y + line
    for i, d in enumerate(run.tools):
        dy = below
        below += line
        info = tools.TOOLS[d]
        if info.active:
            left = charges.get(d, 0) if charges is not None else info.uses
            label = "%s%-10s x%d" % ("[%s] " % "QWRTY"[i] if keys else "", d, left)
            ui.text(surf, label, x, dy, "fg" if not keys else "tan" if left else "dim")
        else:
            ui.text(surf, "%s%-10s daemon" % (pad, d), x, dy, "fg")
        rects[d] = pygame.Rect(x, dy, 30 * ui.cw(), line)
        for s in ui.wrap(info.desc, desc) if desc else ():
            ui.text(surf, s, x, below, "dim", NOTE_SIZE)
            below += ui.lh(NOTE_SIZE)
    if not run.tools:
        ui.text(surf, pad + "(none yet)", x, y + line, "dim")
    return rects


# ------------------------------------------------------------------ title

# The name is set large in the top left. Under it is a hex dump whose ASCII
# pane spells out what the game is: one 16-byte row each, padded so no word
# is split across rows.
TITLE, VERSION = "HEXBREACH", "v1.0"
TITLE_SIZE, VERSION_SIZE = 44, 20
TITLE_ROWS = [b"a hex-dump      ", b"netrunning      ", b"roguelike.      "]
TITLE_PICK = (2, 9)         # the bytes selected to begin with: "hex-dump"


class TitleDump(HexView):
    """The title's dump. It behaves like any other: the cursor links the two
    panes and a drag moves the selection. Read-only."""

    def __init__(self, x, y):
        super().__init__(x, y, rows=len(TITLE_ROWS), size=20)
        self.data = b"".join(TITLE_ROWS)
        self.select_mode = "drag"
        self.chosen = TITLE_PICK

    def handle_event(self, ev):
        for action in super().handle_event(ev):
            self.chosen = action[1:]            # a finished drag (or a click) moves the selection
        return []

    def draw(self, surf):
        lo, hi = self.sel or self.chosen
        self.styles = {i: "sel" for i in range(lo, hi + 1)}
        super().draw(surf)


class TitleScene(Scene):
    X, Y_TITLE, Y_DUMP = 80, 40, 108

    def __init__(self, game):
        super().__init__(game)
        self.t = 0.0
        self.dump = TitleDump(self.X, self.Y_DUMP)
        self.resume()

    def boot(self):
        """Type the screen out again, as on launch. Used after a run ends; coming
        back from a menu does not retype it."""
        self.typing = 0.0

    def owns_drag(self, pos):
        return self.dump.index_at(pos) is not None

    def resume(self, index=None):
        # until the tutorial has been played it is the item under the cursor
        new = not self.game.save.data["tutorial"]
        self.menu = ui.Menu([
            {"label": "NEW RUN"},
            {"label": "TUTORIAL"},
            {"label": "LOGS"},
            {"label": "MENU", "key": "M"},
        ], 80, 300, size=18, width=60, gap=1)
        self.menu.index = index if index is not None else 1 if new else 0

    def handle_event(self, ev):
        self.dump.handle_event(ev)
        choice = self.menu.handle_event(ev)
        if choice == 0:
            self.game.push(ModeScene(self.game))
        elif choice == 1:
            self.game.push(TutorialScene(self.game))
        elif choice == 2:
            self.game.push(LogsScene(self.game))
        elif choice == 3:
            self.game.push(MenuScene(self.game))
        elif ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            self.game.running = False

    def update(self, dt):
        self.t += dt

    def draw(self, surf):
        surf.fill(ui.BLACK)
        self.draw_path(surf)
        x = self.X
        end = ui.text(surf, TITLE, x, self.Y_TITLE, "fg", TITLE_SIZE)
        # the version, small, on the line the name stands on
        drop = ui.font(TITLE_SIZE).get_ascent() - ui.font(VERSION_SIZE).get_ascent()
        ui.text(surf, VERSION, end + 2 * ui.cw(VERSION_SIZE), self.Y_TITLE + drop, "dim", VERSION_SIZE)
        self.dump.draw(surf)
        self.menu.draw(surf)

        d = self.game.save.data
        sy = self.menu.bottom + 30
        ui.text(surf, "OPERATOR RECORD", x, sy, "amber")
        best = "  ".join("%s %s" % (m, ui.clock(s)) for m, s in sorted(d["best_run"].items())) or "none yet"
        rows = [
            "runs %d   full clears %d   deepest subnet %d/%d   IDS evaded %d" % (
                d["runs"], d["wins"], d["deepest_subnet"], runmod.SUBNETS, d["ids_evaded"]),
            "tools unlocked %d/%d   log entries %d/%d   file signatures %d/%d" % (
                len(d["unlocked"]), len(tools.TOOLS), len(d["manual"]), len(packets.FIELD_INFO),
                sum(name in SIGNATURES for name in d["signatures"]), len(SIGNATURES)),
            "best full clear: %s" % best,
        ]
        for i, row in enumerate(rows):
            ui.text(surf, row, x, sy + (i + 1) * ui.lh() + 4, "fg")


# ---------------------------------------------------------------- tutorial

def tutorial_frame():
    """The frame the tutorial is played on: a real HTTP request, built by the
    same code that makes PROTOCOL mode's packets."""
    return packets.parse(packets.frame_tcp(
        "3c:22:fb:4a:1d:07", "f4:5c:89:b2:6e:90", "192.168.1.42", "93.184.216.34", 51515, 80,
        ttl=128, ident=0x1C46, seq=0x1F2E3D4C, ack=0x5A6B7C8D, flags=packets.TCP_PSH | packets.TCP_ACK,
        window=502, payload=packets.build_http_request("GET", "/hello", "example.com")))


class TutorialScene(Scene):
    """Five steps on one frame: offsets, the two panes, selecting a field,
    typing a value, and what a run is. No timer and nothing to lose."""
    HEX_X, HEX_Y = 24, 98
    PANEL_X = 860
    ROWS = 6

    def __init__(self, game):
        super().__init__(game)
        pkt = tutorial_frame()
        data, f = pkt.raw, pkt.fields
        proto, src, ttl, method = f["ip.proto"], f["ip.src"], f["ip.ttl"], f["http.method"]
        ip = pkt.layer_range("IPv4")[0]
        row, col = proto.start // 16 * 16, proto.start % 16
        # want: the input that completes the step. miss: the nudge after a wrong one.
        self.steps = [
            {"title": "OFFSETS",
             "task": "Click the byte at offset 0x%04X." % proto.start,
             "text": ["This is a hex dump of one captured frame, the way Wireshark's packet bytes pane shows it.",
                      "The left column is the offset of the first byte in each row. The top line numbers the columns.",
                      "Offset = row + column: 0x%04X is row %04X, column %02X." % (proto.start, row, col)],
             "want": ("click", proto.start),
             "miss": "Row %04X, column %02X." % (row, col),
             "done": "0x%04X holds %02X. It is the IPv4 Protocol field, and 06 means the packet carries TCP." % (
                 proto.start, data[proto.start])},
            {"title": "HEX AND ASCII",
             "task": "Find the text %s in the ASCII pane and click its first letter." % method.value,
             "text": ["Each byte is written as two hexadecimal digits, 00 to FF.",
                      "The pane on the right shows the same bytes as ASCII characters. A dot is a byte that is not",
                      "a printable character. Move the mouse over a byte: the cursor marks it in both panes."],
             "want": ("click", method.start),
             "miss": "Look in the right-hand pane, row %04X." % (method.start // 16 * 16),
             "done": "%02X is the ASCII code for %s. This is where the HTTP request begins." % (
                 data[method.start], chr(data[method.start]))},
            {"title": "FIELDS",
             "task": "Drag from 0x%04X to 0x%04X to select the IPv4 Source Address." % (src.start, src.end - 1),
             "text": ["A header is a series of fields: runs of bytes with a set position and size.",
                      "The IPv4 header of this frame starts at 0x%04X. Its Source Address field is +0x%02X into it," % (
                          ip, src.start - ip),
                      "at 0x%04X, and is %d bytes long." % (src.start, src.end - src.start)],
             "want": ("select", src.start, src.end - 1),
             "miss": "Press on 0x%04X, drag to 0x%04X, release." % (src.start, src.end - 1),
             "done": "%s is %s: one byte for each number in the address." % (
                 puzzles.base.hexs(data[src.start:src.end]), src.value)},
            {"title": "VALUES",
             "task": "Type the value of the byte at offset 0x%04X." % ttl.start,
             "text": ["Some nodes ask for a byte value. Values are typed in hex, two digits per byte.",
                      "The byte at 0x%04X is the IPv4 Time to Live field." % ttl.start],
             "want": ("type", "%02x" % data[ttl.start]),
             "miss": "Row %04X, column %02X. Type the two digits you see there." % (
                 ttl.start // 16 * 16, ttl.start % 16),
             "done": "0x%02X is %d in decimal: this packet can cross %d routers before it is discarded." % (
                 data[ttl.start], data[ttl.start], data[ttl.start])},
            {"title": "THE RUN",
             "task": "That is everything you need.",
             "text": ["A run is five subnets. Every node on the way is a puzzle played on a dump like this one,",
                      "against a timer. A mistake or a timeout raises TRACE. At 100% you are traced and the run ends.",
                      "Nodes start easy and get harder with every hop. Each new kind of node briefs you before",
                      "its timer starts.",
                      "",
                      "Along the way you pick up tools: software that helps. That is what such programs are really",
                      "called. A tool that acts on the target is traceable: carrying it makes every TRACE gain",
                      "bigger. Credits, the black market and the limit on how many tools you can run at once",
                      "(tool slots) are rules of this game, not real things."],
             "want": None, "miss": "", "done": ""},
        ]
        self.hex = HexView(self.HEX_X, self.HEX_Y, rows=self.ROWS)
        self.hex.data = data
        self.i = -1
        self._next()

    # ---- state the bot and the tests read
    @property
    def step(self):
        return self.steps[self.i]

    @property
    def want(self):
        return self.step["want"]

    def owns_drag(self, pos):
        return not self.solved and self.hex.select_mode == "drag" and self.hex.index_at(pos) is not None

    def root(self):
        return self.game.pop

    def crumbs(self):
        name = "%d-%s" % (self.i + 1, self.step["title"].lower().replace(" ", "-"))
        return [("tutorial", self.restart if self.i else None), (name, None)]

    def restart(self):
        self.i = -1
        self._next()

    def _next(self):
        self.i += 1
        if self.i == len(self.steps):
            self.game.save.data["tutorial"] = True
            self.game.save.write()
            return self.game.pop()
        want = self.want
        self.solved = want is None
        self.misses = 0
        self.typed = ""
        self.note = ("", "dim")
        self.flash = 0.0
        self.hold = 0.3                 # ignore the click that finished the last step
        self.hex.sel = self.hex._anchor = None
        self.hex.select_mode = "drag" if want and want[0] == "select" else "click"

    def _target(self):
        want = self.want
        if want is None or want[0] == "type":
            return range(0)
        return range(want[1], want[-1] + 1)

    def _attempt(self, got, said):
        """got: the input made. said: what to tell the player it was."""
        if got == self.want:
            self.solved, self.hold = True, 0.3
            self.note = (self.step["done"], "tan")
            return
        self.misses += 1
        self.typed = ""
        self.note = ("%s %s" % (said, self.step["miss"]), "red")
        if self.misses >= 2:
            self.flash = 3.0

    # ---- input
    def handle_event(self, ev):
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            return self.game.pop()
        if self.solved:
            self.hex.handle_event(ev)           # still free to look around
            if self.hold <= 0 and ((ev.type == pygame.KEYDOWN and ev.key in CONFIRM) or (
                    ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1)):
                self._next()
            return
        want = self.want
        if want[0] == "type" and ev.type == pygame.KEYDOWN:
            ch = (ev.unicode or "").lower()
            if ev.key == pygame.K_BACKSPACE:
                self.typed = self.typed[:-1]
            elif len(ch) == 1 and ch in puzzles.base.HEX_DIGITS:
                self.typed += ch
                if len(self.typed) == 2:
                    self._attempt(("type", self.typed), "%s is not it." % self.typed.upper())
            return
        for action in self.hex.handle_event(ev):
            if want[0] == "type":
                self.note = ("Type it on the keyboard: two hex digits.", "dim")
            elif action[0] == "click":
                self._attempt(action, "That is offset 0x%04X." % action[1])
            else:
                self._attempt(action, "You selected 0x%04X to 0x%04X." % (action[1], action[2]))

    def update(self, dt):
        self.hold = max(0.0, self.hold - dt)
        self.flash = max(0.0, self.flash - dt)
        self.hex.update(dt)
        style = "found" if self.solved else "flash" if self.flash > 0 else None
        self.hex.styles = {i: style for i in self._target()} if style else {}

    # ---- drawing
    def draw(self, surf):
        step, hx = self.step, self.hex
        surf.fill(ui.BLACK)
        self.draw_path(surf)
        ui.text_right(surf, "%d/%d" % (self.i + 1, len(self.steps)), ui.W - 24 - 12 * ui.cw(), 10, "dim")
        ui.text_right(surf, "ESC leave", ui.W - 24, 10, "dim")
        ui.text(surf, step["task"], self.HEX_X, 64, "amber", 18)
        hx.draw(surf)

        # name the three parts of the dump underneath it
        y = hx.y + (self.ROWS + 1) * hx.lh + 6
        for x, label in ((hx.x, "offset"), (hx.x_hex, "hex: two digits per byte"), (hx.x_ascii, "ASCII")):
            ui.text(surf, label, x, y, "dim", 14)

        y += 3 * ui.lh()
        for row in step["text"]:
            ui.text(surf, row, self.HEX_X, y, "fg")
            y += ui.lh()
        y += ui.lh()
        if self.want and self.want[0] == "type" and not self.solved:
            ui.text(surf, "VALUE > %s" % (self.typed.upper() + "__")[:2], self.HEX_X, y, "tan")
            y += ui.lh()
        ui.text(surf, self.note[0], self.HEX_X, y, self.note[1])
        if self.solved:
            last = self.i == len(self.steps) - 1
            ui.text(surf, "[SPACE] %s" % ("finish" if last else "next"), self.HEX_X, y + 2 * ui.lh(), "tan")

        # what the cursor is on, in every notation
        x, y, line = self.PANEL_X, self.HEX_Y, ui.lh()
        ui.text(surf, "UNDER THE CURSOR", x, y, "amber")
        i = hx.hover
        if i is None or i >= len(hx.data):
            ui.text(surf, "  move the mouse over a byte", x, y + line, "dim")
            return
        b = hx.data[i]
        rows = ["offset   0x%04X" % i, "hex      %02X" % b, "decimal  %d" % b,
                "binary   %s %s" % (format(b >> 4, "04b"), format(b & 15, "04b")),
                "ASCII    %s" % (chr(b) if 32 <= b < 127 else ".  (not printable)")]
        for n, row in enumerate(rows):
            ui.text(surf, "  " + row, x, y + (n + 1) * line, "fg")


# ------------------------------------------------------------------- run

class ModeScene(Scene):
    MODES = [
        ("RAW", "Random bytes. Nothing to learn, just a game. PAYLOAD, HUNT, XOR, CARVE and REASSEMBLE only."),
        ("PROTOCOL", "Synthesized, valid packets: Ethernet, IPv4, TCP, UDP, DNS, HTTP. Play it "
                     "long enough and you can read Wireshark's packet bytes pane."),
        ("LIVE", "Your own captures. Drop .pcap / .pcapng files into captures/. Everything "
                 "stays on this machine."),
    ]

    def __init__(self, game):
        super().__init__(game)
        self.live = sources.PcapSource(game.captures_dir)
        items = []
        for mode, desc in self.MODES:
            if mode == "LIVE":
                desc += " [%s]" % self.live.describe()
            items.append({"label": mode, "desc": desc})
        items.append({"label": "BACK"})
        self.menu = ui.Menu(items, 80, 150, size=18, width=78)

    def root(self):
        return self.game.pop

    def crumbs(self):
        # the path follows the cursor: the directory you would be stepping into
        return [(mode.lower(), None) for mode, _ in self.MODES[self.menu.index:self.menu.index + 1]]

    def handle_event(self, ev):
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            return self.game.pop()
        choice = self.menu.handle_event(ev)
        if choice is None:
            return
        if choice == 3:
            return self.game.pop()
        mode = self.MODES[choice][0]
        source = self.live if mode == "LIVE" else sources.make_source(mode)
        self.game.start_run(mode, source)

    def draw(self, surf):
        surf.fill(ui.BLACK)
        self.draw_path(surf)
        ui.text(surf, "SELECT DATA MODE", 80, 80, "amber", 18)
        ui.text(surf, "where the bytes come from for this run", 80, 108, "dim")
        self.menu.draw(surf)
        y = self.menu.bottom + 20
        for err in self.live.errors[:4]:
            ui.text(surf, "skipped " + err[:100], 80, y, "red")
            y += ui.lh()


class ToolkitScene(Scene):
    """Pick one free tool before the run starts."""

    def __init__(self, game, run):
        super().__init__(game)
        self.run = run
        self.stock = run.shop_stock(random.Random(run.seed), 3)
        self.menu = ui.Menu([{"label": d, "desc": tools.describe(d)} for d in self.stock],
                            80, 170, size=18, width=78)

    def root(self):
        return self.game.pop            # nothing has happened yet: the run is simply dropped

    def crumbs(self):
        return [(self.run.mode.lower(), self.back), ("toolkit", None)]

    def back(self):
        """Back to the choice of data mode, with this run's mode under the cursor."""
        modes = ModeScene(self.game)
        modes.menu.index = [mode for mode, _ in ModeScene.MODES].index(self.run.mode)
        self.game.replace(modes)

    def handle_event(self, ev):
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            return self.back()
        choice = self.menu.handle_event(ev)
        if choice is not None:
            self.run.install(self.stock[choice])
            self.game.replace(MapScene(self.game, self.run))

    def draw(self, surf):
        surf.fill(ui.BLACK)
        self.draw_path(surf)
        ui.text(surf, "TOOLKIT", 80, 80, "amber", 18)
        ui.text(surf, "Pick a tool.", 80, 108, "dim")
        self.menu.draw(surf)
        ui.text(surf, "ESC back", 80, ui.H - 30, "dim")


# -------------------------------------------------------------------- map

MAP_SIZE = 14
COL_W = 22          # characters per layer
SLOT_H = 4          # text rows per slot
NAME_W = 15
N, E, S, WEST = 1, 2, 4, 8        # arms of a box-drawing character: its index in ui.BOX


def _route(mask, a, b):
    """Add the line from node a to node b (one layer on) to a cell mask.
    Leaves a's name row, runs to a channel column that is unique to a's slot,
    turns up or down it, and arrives on b's label row."""
    x0 = a.layer * COL_W
    ra, rb = a.slot * SLOT_H + 1, b.slot * SLOT_H
    start = x0 + min(NAME_W, len(_short(a.name)) + 1)
    chan, end = x0 + NAME_W + 1 + a.slot, x0 + COL_W - 1

    def put(c, r, bits):
        mask[(c, r)] = mask.get((c, r), 0) | bits

    for c in range(start, chan):
        put(c, ra, E | WEST)
    put(chan, ra, WEST)
    top, bottom = min(ra, rb), max(ra, rb)
    for r in range(top, bottom + 1):
        put(chan, r, (N if r > top else 0) | (S if r < bottom else 0))
    put(chan, rb, E)
    for c in range(chan + 1, end + 1):
        put(c, rb, E | WEST)


def _short(name):
    """Node name as it fits under a map label: drop the port before truncating."""
    if len(name) > NAME_W and ":" in name:
        name = name.rsplit(":", 1)[0]
    return name if len(name) <= NAME_W else name[:NAME_W - 1] + "\u2026"


def _mask_rows(mask):
    width, height = (runmod.LAYERS + 1) * COL_W, runmod.SLOTS * SLOT_H
    return ["".join(ui.BOX[mask.get((c, r), 0)] for c in range(width)).rstrip() for r in range(height)]


class MapScene(Scene):
    X, Y = 40, 110
    TOOLS_W = 46        # characters across the tools panel, bottom right
    HOVER_DELAY = 0.6   # seconds the mouse rests on a node before its briefing pops up

    def __init__(self, game, run):
        super().__init__(game)
        self.run = run
        self.log = ui.Log(keep=2000)    # the session log: everything that has happened this run
        self._wheel = 0.0
        self.hover = None
        self.hover_since = 0.0      # restarts the cursor blink
        self.sel = 0                # the node the arrow keys are on, as an index into run.available()
        self.keys = False           # the arrow keys moved last, not the mouse: no popup
        self._preview = None        # (key, PuzzleScene) for the briefing popup
        self.still_since = 0.0      # when the mouse last moved
        self._popped = None         # the node whose popup is up: it stays while the mouse stays on it
        self._popup_box = None      # where that popup was drawn
        self.abandon = 0.0
        self.t = 0.0
        self._shop_rect = pygame.Rect(0, 0, 0, 0)     # set when drawn
        self._jumps = []            # (rect, subnet level) of the subnet numbers, drawn while god mode is on
        self.log.add("connected. %s mode: %s" % (run.mode, run.source.describe()), "dim")
        self.log.add("pick an entry node on the left edge of the subnet", "fg")
        self._rebuild()         # now, not at the first draw: a click can arrive before that

    def _rect(self, node):
        cw, lh = ui.cw(MAP_SIZE), ui.lh(MAP_SIZE)
        return pygame.Rect(self.X + node.layer * COL_W * cw, self.Y + node.slot * SLOT_H * lh,
                           NAME_W * cw, 2 * lh)

    def _rebuild(self):
        self._subnet = self.run.subnet
        self.node_rects = {n.id: self._rect(n) for n in self._subnet.nodes.values()}
        mask = {}
        for a, b in self._subnet.edges():
            _route(mask, a, b)
        self._all_rows = _mask_rows(mask)

    def _panels(self):
        """What goes below the map: the node under the cursor and the session
        log on the left, the tools on the right. Returns the top of both, the
        tools' x, the characters across the left side, the log's y and its rows."""
        line = ui.lh()
        top = self.Y + runmod.SLOTS * SLOT_H * ui.lh(MAP_SIZE) + 16
        tools_x = ui.W - 40 - self.TOOLS_W * ui.cw()
        log_y = top + 2 * line
        return top, tools_x, (tools_x - 24 - 40) // ui.cw(), log_y, max(1, (ui.H - 38 - log_y) // line - 1)

    def look_back(self, by):
        """Scroll the session log: back through what happened, or forward again."""
        _, _, width, _, rows = self._panels()
        self.log.scroll_by(by, rows, width)

    def enter(self, node):
        run, game = self.run, self.game
        run.move_to(node)
        if node.kind == "FOOTHOLD":
            game.push(FootholdScene(game, run, node))
        else:
            game.push(PuzzleScene.open(game, run, node, run.node_level(node), brief=False))

    def handle_event(self, ev):
        run = self.run
        if run.over:
            return
        avail = run.available()
        if ev.type == pygame.MOUSEMOTION:
            before = self.hover
            self.still_since = time.monotonic()
            self.hover = self._pointed(ev.pos)
            if self.hover is not before:
                self.hover_since = time.monotonic()
                self._popped = None
            self.keys = False
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if run.god:
                # god mode: any subnet, and any node on the map, not only the next ones
                for rect, level in self._jumps:
                    if rect.collidepoint(ev.pos):
                        return self.jump(level)
                node = self._pointed(ev.pos)
                if node is not None:
                    return self.enter(node)
            for node in avail:
                if self.node_rects[node.id].collidepoint(ev.pos):
                    return self.enter(node)
            if self._shop_rect.collidepoint(ev.pos):
                return self.game.push(ShopScene(self.game, run))
        elif ev.type == pygame.MOUSEWHEEL:
            # trackpads send many small fractional steps: accumulate them
            self._wheel += getattr(ev, "precise_y", ev.y) * 2
            rows = int(self._wheel)
            self._wheel -= rows
            self.look_back(rows)
        elif ev.type == pygame.KEYDOWN:
            page = self._panels()[4]
            step = {pygame.K_PAGEUP: page, pygame.K_PAGEDOWN: -page,
                    pygame.K_HOME: len(self.log.lines) * 9, pygame.K_END: -len(self.log.lines) * 9}.get(ev.key)
            move = {pygame.K_UP: -1, pygame.K_LEFT: -1, pygame.K_DOWN: 1, pygame.K_RIGHT: 1}.get(ev.key)
            if ev.key == pygame.K_ESCAPE:
                self.leave()
            elif ev.key == pygame.K_b:
                self.game.push(ShopScene(self.game, run))
            elif move and avail:
                # the arrow keys pick among the nodes you can reach, top to bottom
                self.sel = (self._sel(avail) + move) % len(avail)
                self.keys, self.hover = True, None
                self.hover_since = time.monotonic()
            elif ev.key in CONFIRM and avail:
                self.enter(avail[self._sel(avail)])
            elif step:
                self.look_back(step)
            elif ev.unicode and ev.unicode.isdigit():
                i = int(ev.unicode) - 1
                if 0 <= i < len(avail):
                    self.enter(avail[i])

    def _pointed(self, pos):
        """The node drawn at pos, or None. A node hidden under the popup cannot
        be pointed at through it; the node the popup belongs to still can."""
        if (self._popup_box is not None and self._popup_box.collidepoint(pos)
                and not (self.hover and self.node_rects[self.hover.id].collidepoint(pos))):
            return None
        return next((n for n in self.run.subnet.nodes.values()
                     if self.node_rects.get(n.id) and self.node_rects[n.id].collidepoint(pos)), None)

    def jump(self, level):
        """God mode: go straight to a subnet."""
        if self.run.jump(level):
            self._rebuild()         # now: a click can arrive before the next draw
            self.hover, self.sel = None, 0
            self.run.note("GOD MODE: jumped to subnet %d" % level, "tan")

    def _draw_jumps(self, surf):
        """God mode: the subnets, in the top right. The one you are in is lit; a click on another goes to it."""
        self._jumps = []
        if not self.run.god:
            return
        cw, wide = ui.cw(), 3
        x = ui.W - 24 - wide * runmod.SUBNETS * cw
        ui.text_right(surf, "SUBNET", x - cw, 34, "dim")
        for level in range(1, runmod.SUBNETS + 1):
            rect = pygame.Rect(x, 34, wide * cw, ui.lh())
            if level == self.run.level:
                ui.text(surf, " %d " % level, x, 34, "bg", bg="amber")
            else:
                ui.text(surf, " %d " % level, x, 34, "tan" if rect.collidepoint(self.path.mouse) else "amber")
            self._jumps.append((rect, level))
            x += wide * cw

    def _sel(self, avail):
        return min(self.sel, len(avail) - 1)

    def focus(self):
        """The node being looked at: under the mouse, or else the one the arrow keys are on."""
        avail = self.run.available()
        if self.hover is not None:
            return self.hover
        return avail[self._sel(avail)] if avail else None

    def preview(self):
        """The briefing to pop up, once the mouse has rested on a node; None otherwise."""
        node, now = self.hover, time.monotonic()
        if (node is None or self.keys or node.done
                or (node.kind not in puzzles.REGISTRY and node.kind != "IDS")):
            return None
        # the full wait every time, with the mouse still: sweeping across nodes pops nothing up
        if node is not self._popped and min(now - self.hover_since, now - self.still_since) < self.HOVER_DELAY:
            return None
        self._popped = node
        key = (node.id, node.seed, tuple(self.run.tools), self.run.level, self.run.solved.get(node.kind, 0))
        if self._preview is None or self._preview[0] != key:
            try:
                scene = PuzzleScene.open(self.game, self.run, node, self.run.node_level(node))
            except puzzles.PuzzleUnavailable:
                return None
            self._preview = (key, scene)
        return self._preview[1]

    def crumbs(self):
        return run_crumbs(self.run, self.leave)

    def root(self):
        return self.leave

    def leave(self):
        """Going back up from the map means giving up the run, so it has to be asked for twice."""
        if self.run.over:
            return
        if self.abandon > 0:
            self.run.over = "traced"
            self.run.abandoned = True
        else:
            self.abandon = 2.5
            self.log.add("that abandons the run: press ESC (or click the path) again to do it", "red")

    def update(self, dt):
        self.t += dt
        self.abandon = max(0.0, self.abandon - dt)
        run = self.run
        if self._subnet is not run.subnet:
            self._rebuild()
            self.hover = None
            self.sel = 0
        shown = self.preview()
        if shown is not None:
            shown.briefed += dt         # the example plays while the popup is up
        for note in run.notes:
            self.log.add(*note)
        run.notes.clear()
        if run.over:
            return end_run(self.game, run)
        run.tick(dt)

    def draw(self, surf):
        run = self.run
        if self._subnet is not run.subnet:
            self._rebuild()
        surf.fill(ui.BLACK)
        draw_header(self, surf, run)
        self._draw_jumps(surf)
        cw, lh = ui.cw(MAP_SIZE), ui.lh(MAP_SIZE)
        for layer in range(runmod.LAYERS + 1):
            label = "IDS" if layer == runmod.LAYERS else "HOP %d" % (layer + 1)
            ui.text(surf, label, self.X + layer * COL_W * cw, self.Y - lh - 8, "dim", MAP_SIZE)

        avail = run.available()
        for r, row in enumerate(self._all_rows):
            ui.text(surf, row, self.X, self.Y + r * lh, "dim", MAP_SIZE)
        # the way in so far is lit, node to node; the ways on from here are amber
        # (every link between two nodes that are done: god mode can leave gaps in the way in)
        path, trail = run.path(), {}
        for a in path:
            for b in a.next:
                if run.subnet.nodes[b].done:
                    _route(trail, a, run.subnet.nodes[b])
        for r, row in enumerate(_mask_rows(trail)):
            ui.text(surf, row, self.X, self.Y + r * lh, "fg", MAP_SIZE)
        if run.position is not None:
            hot = {}
            for node in avail:
                _route(hot, run.position, node)
            for r, row in enumerate(_mask_rows(hot)):
                ui.text(surf, row, self.X, self.Y + r * lh, "amber", MAP_SIZE)

        blink = int(self.t * 3) % 2 == 0
        focus = self.focus()
        for node in run.subnet.nodes.values():
            rect = self.node_rects[node.id]
            label = "[%s]" % node.kind
            if node in avail:
                n = avail.index(node) + 1
                c = "red" if node.kind == "IDS" else "amber"
                if node is focus and ui.blink(self.hover_since):
                    ui.text(surf, label, rect.x, rect.y, "bg", MAP_SIZE, bg="tan")
                elif node is focus:
                    ui.text(surf, label, rect.x, rect.y, "tan", MAP_SIZE)
                else:
                    ui.text(surf, label, rect.x, rect.y, c, MAP_SIZE)
                ui.text(surf, " %d%s" % (n, "<" if blink else " "), rect.x + len(label) * cw, rect.y, c, MAP_SIZE)
                ui.text(surf, _short(node.name), rect.x, rect.y + lh, c, MAP_SIZE)
            elif run.god and node is focus:             # god mode: any node can be gone to
                if ui.blink(self.hover_since):
                    ui.text(surf, label, rect.x, rect.y, "bg", MAP_SIZE, bg="tan")
                else:
                    ui.text(surf, label, rect.x, rect.y, "tan", MAP_SIZE)
                if node is run.position:
                    ui.text(surf, " @", rect.x + len(label) * cw, rect.y, "fg", MAP_SIZE)
                ui.text(surf, _short(node.name), rect.x, rect.y + lh, "tan", MAP_SIZE)
            elif node.done or node is run.position:     # on the path taken: lit, with @ where you are now
                ui.text(surf, label + (" @" if node is run.position else ""), rect.x, rect.y, "fg", MAP_SIZE)
                ui.text(surf, _short(node.name), rect.x, rect.y + lh, "fg", MAP_SIZE)
            else:
                c = "dim" if run.position and node.layer <= run.position.layer else (
                    "red" if node.kind == "IDS" else "fg")
                ui.text(surf, label, rect.x, rect.y, c, MAP_SIZE)
                ui.text(surf, _short(node.name), rect.x, rect.y + lh, "dim", MAP_SIZE)

        # below the map, on the left: the node under the cursor, then the session log
        y, tools_x, width, log_y, rows = self._panels()
        line = ui.lh()
        node = focus
        if node is not None:
            x = ui.text(surf, "%s  %s" % (node.kind, node.name), 40, y, "amber")
            if node.kind != "FOOTHOLD":
                pay = "pays about %d credits" % run.reward(node.kind, 0.5, run.node_level(node))
                ui.text(surf, pay, x + 3 * ui.cw(), y, "dim")

        total = len(self.log.rows(width))
        x = ui.text(surf, "SESSION LOG", 40, log_y, "dim") + 3 * ui.cw()
        if total > rows:
            last = total - self.log.scroll
            x = ui.text(surf, "%d-%d of %d" % (last - rows + 1, last, total), x, log_y, "dim") + 3 * ui.cw()
            if self.log.scroll:
                ui.text(surf, "%d newer below" % self.log.scroll, x, log_y, "tan")
        self.log.draw(surf, 40, log_y + line, rows, width=width)

        # on the right: the tools, each with what it does
        draw_tools(surf, run, tools_x, y, keys=False, desc=self.TOOLS_W * ui.cw() // ui.cw(NOTE_SIZE))
        label = "[B] BLACK MARKET"
        self._shop_rect = pygame.Rect(ui.W - 40 - len(label) * ui.cw(), y, len(label) * ui.cw(), line)
        ui.text_right(surf, label, ui.W - 40, y, "amber")

        shown = self.preview()
        self._popup_box = None
        if shown is not None:
            rect = self.node_rects[self.hover.id]
            self._popup_box = shown.draw_popup(surf, rect.right + 12, rect.y)


# ----------------------------------------------------------------- puzzle

POPUP_W = 76                # characters across the briefing popup on the map
OVERTIME_TICK = 0.5         # seconds between TRACE rises once time is up
OVERTIME_TICKS = 8          # ticks of overtime that add up to the node's old one-off timeout cost
OVERTIME_PAY = 0.5          # what a node finished in overtime pays, as a share of its base
SEVERITY_NOTE = {puzzles.NEAR: "  near miss", puzzles.WRONG: "", puzzles.WILD: "  wild guess"}
PANEL_W = 41                # characters across the side panel
TASK_MARKS = {"done": ("[x]", "dim"), "now": ("[>]", "amber"), "todo": ("[ ]", "fg")}
TOOL_KEYS = [(pygame.K_q, pygame.K_F1), (pygame.K_w, pygame.K_F2), (pygame.K_r, pygame.K_F3),
               (pygame.K_t, pygame.K_F4), (pygame.K_y, pygame.K_F5)]


class PuzzleScene(Scene):
    HEX_X, HEX_Y = 24, 98
    PANEL_X, PANEL_Y = 860, 98
    LOG_Y = 656

    @classmethod
    def open(cls, game, run, node, level, brief=True):
        """The scene for a node and its puzzle, made from the node's seed. With
        brief=False the timer starts at once: the map already showed the briefing."""
        if node.kind == "IDS":
            p = puzzles.ids.generate(node.seed, run.source, level)
            scene = cls(game, run, node, p, level, p.modifiers, p.time_limit)
        else:
            p = puzzles.generate(node.kind, node.seed, run.source, level, run.solved.get(node.kind, 0))
            scene = cls(game, run, node, p, level)
        if not brief:
            scene.jack_in()
        return scene

    def jack_in(self):
        self.phase = "play"
        self.log.add("jacked in: %s %s" % (self.node.kind, self.node.name), "dim")

    def __init__(self, game, run, node, puzzle, level, modifiers=(), time_limit=None):
        super().__init__(game)
        self.run, self.node = run, node
        self.puzzle = puzzle
        self.level = level              # difficulty the node was generated at
        self.is_boss = node.kind == "IDS"
        self.mistake_cost = run.mistake_cost(level)                 # an ordinary mistake; near misses and
        self.mistake_range = (run.mistake_cost(level, puzzles.NEAR),    # wild guesses cost less and more
                              run.mistake_cost(level, puzzles.WILD))
        self.timeout_cost = run.timeout_cost(level, ids=self.is_boss)
        # out of time is overtime: TRACE rises a little every OVERTIME_TICK until you finish or jack out
        self.overtime = False
        self.overtime_clock = 0.0
        self.overtime_trace = 0.0       # TRACE taken in overtime so far
        self.modifiers = list(modifiers)
        self.live_mods = tools.active_modifiers(run.tools, self.modifiers)
        self.total = tools.time_limit(run.tools, time_limit or puzzle.time_limit)
        self.left = self.total
        self.freeze = 0.0
        self.charges = tools.node_charges(run.tools)
        self.phase = "brief"            # brief -> play -> result
        self.result = None              # solved / skipped / jacked out / traced
        self.banner = ("", "fg")
        self.had_mistake = False
        self.mistakes = 0               # made on this node: each one eats into the accuracy bonus
        self.last_cost = 0.0            # TRACE from the latest mistake, for SNAPSHOT
        self.red = 0.0
        self.briefed = 0.0              # seconds the briefing has been up: the clock its example plays on
        self.log = ui.Log(echo=run.note)        # everything said here goes into the run's session log too
        self.hex = HexView(self.HEX_X, self.HEX_Y, rows=24)
        self.panel_hits = []
        self.tool_rects = {}
        self._load()

    @property
    def factor(self):
        """How hard this node came out, and the rank it ended at: scales its
        base pay. An IDS pays by its own rule."""
        if self.is_boss:
            return 1.0
        p = self.puzzle
        return p.difficulty() * (p.rank[1] if p.rank else 1.0)

    def _load(self):
        p, hx, mods = self.puzzle, self.hex, self.live_mods
        hx.reset()
        hx.cols = p.cols
        hx.select_mode = p.select_mode
        hx.hide_ascii = "BLACKOUT" in mods
        hx.hide_offsets = "BLIND" in mods
        hx.dark = "DARK" in mods
        hx.loss = "LOSS" in mods
        hx.throttle = "THROTTLE" in mods
        self._sync()

    def _sync(self):
        p, hx = self.puzzle, self.hex
        hx.data = p.display()
        hx.styles = p.styles()
        hx.bands = p.layers() if self.run.has("DISSECTOR") else []
        hx.codepage = p.codepage = self.run.has("CODEPAGE")
        p.drag = hx.dragging if self.phase == "play" else None

    @property
    def menu_ok(self):
        return self.phase != "play"     # not while the timer runs: no looking things up mid-node

    def owns_drag(self, pos):
        return self.phase == "play" and self.hex.select_mode in ("drag", "move") and self.hex.index_at(pos) is not None

    # ---- the path line
    def crumbs(self):
        deeper = (self.node.name, self.puzzle.kind.lower())     # ".../ids" for the boss
        # the way back to the map is open until the timer starts
        back = self.back_out if self.phase == "brief" else self.jack_out if self.can_jack_out else None
        return run_crumbs(self.run, None, back, *deeper)

    @property
    def can_jack_out(self):
        return self.phase == "play" and self.overtime

    def jack_out(self):
        """Leave once time is up: the node is not cleared, and the TRACE taken in overtime stays."""
        if self.can_jack_out:
            self._end("jacked out")

    def back_out(self):
        """Leave from the briefing, as if the node had never been entered."""
        self.run.back_out()
        self.game.pop()

    # ---- input
    def handle_event(self, ev):
        if self.phase == "brief":
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                return self.back_out()
            if (ev.type == pygame.KEYDOWN and ev.key in CONFIRM) or (
                    ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1):
                self.jack_in()
            return
        if self.phase == "play" and ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            if self.can_jack_out:
                return self.jack_out()
            self.log.add("no backing out until the timer runs out", "dim")
            return
        if self.phase == "result":
            if (ev.type == pygame.KEYDOWN and ev.key in CONFIRM) or (
                    ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and not self.hex.contains(ev.pos)):
                if self.result == "jacked out":
                    # the node is not cleared: back to the map, and it will be a fresh puzzle next time
                    self.node.seed += 1
                    self.run.back_out()
                    self.game.pop()
                else:
                    self.run.complete(self.node)     # clearing IDS moves on to the next subnet
                    if self.is_boss and not self.run.over:
                        # with the IDS down nobody is watching: the one time there is to shop
                        self.game.replace(ShopScene(self.game, self.run, self.node.seed))
                    else:
                        self.game.pop()
            else:
                self.hex.handle_event(ev)       # still free to look around the solved dump
            return

        p = self.puzzle
        if ev.type == pygame.KEYDOWN:
            for slot, keys in enumerate(TOOL_KEYS):
                if ev.key in keys and slot < len(self.run.tools):
                    return self.activate(self.run.tools[slot])
            if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                return self._handle(p.key("enter"))
            if ev.key == pygame.K_BACKSPACE:
                return self._handle(p.key("backspace"))
            ch = (ev.unicode or "").lower()
            if len(ch) == 1 and ch.isalnum():
                self._handle(p.key(ch))
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            for rect, key in self.panel_hits:
                if rect.collidepoint(ev.pos):
                    return self._handle(p.key(key))
            for d, rect in self.tool_rects.items():
                if rect.collidepoint(ev.pos) and tools.TOOLS[d].active:
                    return self.activate(d)
        for action in self.hex.handle_event(ev):
            if self.phase != "play":
                break
            if action[0] == "click":
                self._handle(self.puzzle.click(action[1]))
            elif action[0] == "move":
                self._handle(self.puzzle.move(action[1], action[2]))
            else:
                self._handle(self.puzzle.select(action[1], action[2]))

    def _drain(self, p):
        for msg in p.messages:
            self.log.add(*msg)
        p.messages.clear()
        save = self.game.save
        for kind, name, example in p.learned:
            if kind == "field":
                if save.learn_field(name, example):
                    layer, label, _ = packets.FIELD_INFO[name]
                    self.log.add("LOGS: new entry, %s > %s" % (layer, label), "tan")
                    self.run.new_fields.append("%s > %s" % (layer, label))
            elif save.learn_signature(name, example):
                self.log.add("LOGS: new signature, %s" % name, "tan")
                self.run.new_fields.append("signature: %s" % name)
        p.learned.clear()

    def _handle(self, res):
        p = self.puzzle
        self._drain(p)
        if res == "mistake":
            cost = tools.trace_cost(self.run.tools, self.run.mistake_cost(self.level, p.severity), "mistake",
                                      first_mistake=not self.had_mistake)
            if self.run.god:
                cost = 0
                self.log.add("GOD MODE: no TRACE for that mistake", "tan")
            elif cost:
                self.log.add("TRACE +%s%%%s" % (ui.pct(cost), SEVERITY_NOTE[p.severity]), "red")
            else:
                self.log.add("SPOOFER took the blame: no TRACE", "tan")
            self.had_mistake = True
            self.mistakes += 1
            self.last_cost = cost
            self.run.stats["mistakes"] += 1
            self.run.add_trace(cost)
            self.red = 0.25
            if self.run.over:
                self._end("traced")
        elif res == "solved":
            self._end("solved")

    def activate(self, d):
        if self.phase != "play":
            return
        if self.charges.get(d, 0) <= 0:
            self.log.add("%s: no charges left on this node" % d, "dim")
            return
        p, run, used = self.puzzle, self.run, False
        if d == "PROXY":
            self.freeze = tools.PROXY_SECONDS
            self.log.add("PROXY: rerouted, trace timer stopped for %ds" % tools.PROXY_SECONDS, "tan")
            used = True
        elif d == "BRUTEFORCE":
            used = p.bruteforce()
            if not used:
                self.log.add("BRUTEFORCE: nothing to try it on here", "dim")
        elif d == "SCANNER":
            used = p.scan()
        elif d == "SNAPSHOT":
            used = p.snapshot()
            if not used and self.last_cost > 0:
                run.add_trace(-self.last_cost)
                self.log.add("SNAPSHOT: last mistake taken back, TRACE -%s%%" % ui.pct(self.last_cost), "tan")
                self.last_cost, used = 0.0, True
                self.mistakes = max(0, self.mistakes - 1)       # and it no longer counts against the pay
            elif not used:
                self.log.add("SNAPSHOT: nothing to undo", "dim")
        elif d == "EXPLOIT":
            if self.is_boss:
                self.log.add("EXPLOIT: there is no ready-made exploit for an IDS", "dim")
            elif run.exploit_used:
                self.log.add("EXPLOIT: already used in this subnet", "dim")
            else:
                run.exploit_used = True
                self.charges[d] -= 1
                return self._end("skipped")
        if used:
            self.charges[d] -= 1
        self._drain(p)

    # ---- outcome
    def _end(self, result):
        run, node, save = self.run, self.node, self.game.save
        self.phase, self.result = "result", result
        self._drain(self.puzzle)
        if result == "solved":
            quick = self.left / self.total
            factor = self.factor * (OVERTIME_PAY if self.overtime else 1.0)
            parts = run.score(node.kind, quick, self.level, self.mistakes, factor)
            credits = run.reward(node.kind, quick, self.level, self.mistakes, factor)
            run.earn(credits)
            run.stats["solved"] += 1
            run.solved[node.kind] = run.solved.get(node.kind, 0) + 1
            cool = tools.after_solve(run.tools)
            run.add_trace(cool)
            what = "IDS EVADED" if self.is_boss else self.puzzle.rank[0] if self.puzzle.rank else "NODE BREACHED"
            text = "%s  +%d credits" % (what, credits)
            if cool:
                text += "  TRACE %d%%" % cool
            if self.overtime:
                text += "  (overtime: half pay)"
            self.banner = (text, "amber")
            self.log.add(*self.banner)
            held = ", +%d from tools" % (credits - sum(parts)) if credits != sum(parts) else ""
            self.log.add("pay: %d base, +%d speed, +%d accuracy%s" % (parts + (held,)), "tan")
            if self.is_boss:
                unlocked = save.record_ids_evaded()
                if unlocked:
                    run.new_unlocks.append(unlocked)
                    run.unlocked.append(unlocked)
                    self.log.add("NEW TOOL UNLOCKED: %s. %s" % (unlocked, tools.describe(unlocked)), "tan")
            elif save.record_solve(node.kind, self.total - self.left):
                self.log.add("fastest %s yet: %.1fs" % (node.kind, self.total - self.left), "tan")
        elif result == "skipped":
            self.banner = ("EXPLOIT: node bypassed, no credits", "tan")
            self.log.add(*self.banner)
        elif result == "jacked out":
            run.stats["failed"] += 1
            # jacking out never gets you through: the node has to be done again
            self.banner = ("JACKED OUT  %s  +%s%% TRACE in overtime" % (
                "IDS NOT EVADED" if self.is_boss else "NODE NOT BREACHED", ui.pct(self.overtime_trace)), "red")
            self.log.add(*self.banner)
        self._sync()
        save.write()
        if self.result == "traced":
            end_run(self.game, run)     # no waiting: the report is up the moment the trace completes

    # ---- frame
    def update(self, dt):
        run, p = self.run, self.puzzle
        self.red = max(0.0, self.red - dt)
        p.tick(dt)
        self.hex.update(dt)
        if self.phase == "brief":
            self.briefed += dt
        if self.phase == "play":
            if self.freeze > 0:
                self.freeze = max(0.0, self.freeze - dt)
            else:
                self.left -= dt
            if self.left <= 0:
                self.left = 0.0
                self._overtime(dt)
        # the clock keeps going here too, briefing and result included
        run.tick(dt)
        if run.over and self.result != "traced":
            if self.phase == "result":
                end_run(self.game, run)     # traced while the result was up
            else:
                self._end("traced")
        self._sync()

    def tick_cost(self):
        """TRACE added each OVERTIME_TICK once time is up, with the tools carried taken into account."""
        if self.run.god:
            return 0
        return tools.trace_cost(self.run.tools, self.timeout_cost / OVERTIME_TICKS, "timeout")

    def _overtime(self, dt):
        if not self.overtime:
            self.overtime = True
            self.red = 0.4
            self.log.add("TIME UP: TRACE +%s%% every %ss.  [ESC] jack out, or finish for half pay" % (
                ui.pct(self.tick_cost()), OVERTIME_TICK), "red")
        if self.freeze > 0:
            return
        self.overtime_clock += dt
        while self.overtime_clock >= OVERTIME_TICK and not self.run.over:
            self.overtime_clock -= OVERTIME_TICK
            cost = self.tick_cost()
            self.run.add_trace(cost)
            self.overtime_trace += cost
        if self.run.over:
            self._end("traced")

    def draw(self, surf):
        run, p = self.run, self.puzzle
        surf.fill(ui.BLACK)
        draw_header(self, surf, run)

        frac = self.left / self.total
        tc = "tan" if self.freeze > 0 else "red" if frac < 0.15 else "amber" if frac < 0.33 else "fg"
        label = "TIME %ds" % math.ceil(self.left)       # whole seconds, rounded up: 0 means it is over
        if self.overtime and self.phase == "play":
            label, tc = "OVERTIME  +%s%% TRACE / %ss" % (ui.pct(self.tick_cost()), OVERTIME_TICK), "red"
        if self.freeze > 0:
            label += "  PAUSED %ds" % math.ceil(self.freeze)
        ui.text_right(surf, label, ui.W - 24, 34, tc)

        if self.phase == "result":
            ui.text(surf, self.banner[0], self.HEX_X, 64, self.banner[1], 18)
            ui.text_right(surf, "[SPACE] %s" % ("back to the map" if self.result == "jacked out" else "continue"),
                          ui.W - 24, 66, "tan")
        elif self.phase == "play":
            ui.text(surf, p.prompt(), self.HEX_X, 64, "amber", 18)
            if self.overtime:
                ui.text_right(surf, "[ESC] jack out", ui.W - 24, 66, "red")
        if self.phase != "brief":
            self.hex.draw(surf)

        # side panel: the steps first, then the puzzle's own lines
        self.panel_hits = []
        if self.phase != "brief":
            line, y = ui.lh(), self.PANEL_Y
            tasks = p.tasks()
            if tasks:
                ui.text(surf, "TASKS", self.PANEL_X, y, "amber")
                y += line
                for text, state in tasks:
                    mark, c = TASK_MARKS[state]
                    for n, row in enumerate(ui.wrap(text, PANEL_W - 4)):
                        ui.text(surf, (mark + " " if n == 0 else "    ") + row, self.PANEL_X, y, c)
                        y += line
                y += line
            for entry in p.panel():
                s, c = entry[0], entry[1]
                ui.text(surf, s[:PANEL_W], self.PANEL_X, y, c)
                if len(entry) > 2:
                    self.panel_hits.append((pygame.Rect(self.PANEL_X, y, PANEL_W * ui.cw(), line), entry[2]))
                y += line
            if self.modifiers:
                y += line
                for m in self.modifiers:
                    live = m in self.live_mods
                    if m == "BLACKOUT" and live:
                        continue            # the hex view says so, in the ASCII pane's place
                    ui.text(surf, "IDS %s%s" % (m, "" if live else " (cancelled)"), self.PANEL_X, y,
                            "red" if live else "dim")
                    y += line
        self.tool_rects = draw_tools(surf, run, self.PANEL_X, self.LOG_Y, self.charges)
        self.log.draw(surf, self.HEX_X, self.LOG_Y, 7, width=80)

        if self.phase == "brief":
            self._draw_brief(surf)
        if self.red > 0:
            ui.outline(surf, "red", (0, 0, ui.W, ui.H), 4)

    BRIEF_LABEL = 10    # characters for the label at the start of a briefing row

    def brief_rows(self):
        """The briefing: a title, a tag, and rows of (label, text, colour) or None
        for a gap. What to do, what is on this node, and the numbers (time, pay).
        Rows are a few words each, never prose."""
        p, run = self.puzzle, self.run
        title = ("%s  %s" % (p.kind, self.node.name), "red" if self.is_boss else "amber")
        tag = p.what.split(":")[0].lower()
        rows = [(label, text, "fg") for label, text in p.brief()]
        # the steps, numbered, under what to do
        rows[1:1] = [("%d." % (n + 1), text, "fg") for n, (text, _) in enumerate(p.tasks())]
        # the IDS view effects, after what the puzzle itself briefs
        for m in self.modifiers:
            if m in self.live_mods:
                rows.append((m, MODIFIERS[m], "red"))
            else:
                rows.append((m, "cancelled by %s" % tools.COUNTERS[m], "dim"))
        # the numbers, with the tools carried taken into account
        def pays(factor):
            low = run.reward(self.node.kind, 0, self.level, mistakes=99, factor=factor)
            high = run.reward(self.node.kind, 1, self.level, factor=factor)
            return "%d to %d" % (low, high)

        ranks = [] if self.is_boss else p.ranks()
        if ranks:       # a kind with ranks: what each pays
            text = ", ".join("%s %s" % (name.split()[0], pays(p.difficulty() * mult)) for name, mult in ranks)
        else:
            text = pays(self.factor)
        rows += [None,
                 ("TIME", "%ds" % self.total, "fg"),
                 ("PAYS", text + " credits", "fg")]
        return title, tag, rows

    def _draw_brief(self, surf):
        """The briefing, in one box. Beside the box, the job plays in miniature."""
        title, tag, rows = self.brief_rows()
        line, cw = ui.lh(), ui.cw()
        box = pygame.Rect(self.HEX_X, self.HEX_Y, self.PANEL_X - 2 * self.HEX_X, (len(rows) + 6) * line)
        ui.outline(surf, "dim", box)
        x, y = box.x + 16, box.y + line
        ui.text(surf, tag, ui.text(surf, title[0], x, y, title[1]) + 3 * cw, y, "dim")
        y += 2 * line
        for i, row in enumerate(rows):
            if row is not None:
                label, text, colour = row
                ui.text(surf, label, x, y + i * line, "dim")
                ui.text(surf, text, x + self.BRIEF_LABEL * cw, y + i * line, colour)
        ui.text(surf, "[SPACE] or click: jack in, and the timer starts     [ESC] back", x, box.bottom - 2 * line, "tan")
        self._draw_example(surf, self.PANEL_X, box.y + line)

    def draw_popup(self, surf, x, y):
        """The briefing as a popup on the map, at about x, y: the rows, then the
        example under them, in one box kept on the screen."""
        title, tag, rows = self.brief_rows()
        line, cw = ui.lh(), ui.cw()
        frames = max((len(r) for _, r in self.puzzle.example()), default=0)
        w = POPUP_W * cw
        h = (len(rows) + frames + 7) * line
        x = max(16, min(x, ui.W - w - 16))
        y = max(16, min(y, ui.H - h - 16))
        box = pygame.Rect(x, y, w, h)
        ui.fill(surf, "bg", box)
        ui.outline(surf, "amber", box)
        x, y = box.x + 16, box.y + line
        ui.text(surf, tag, ui.text(surf, title[0], x, y, title[1]) + 3 * cw, y, "dim")
        y += 2 * line
        for i, row in enumerate(rows):
            if row is not None:
                label, text, colour = row
                ui.text(surf, label, x, y + i * line, "dim")
                ui.text(surf, text[:POPUP_W - self.BRIEF_LABEL - 3], x + self.BRIEF_LABEL * cw, y + i * line, colour)
        self._draw_example(surf, x, y + (len(rows) + 1) * line)
        return box

    def _draw_example(self, surf, x, y):
        """The job in miniature, played on a loop outside the box, where the
        side panel will be."""
        frames = self.puzzle.example()
        if not frames:
            return
        left, rows = self.briefed % sum(secs for secs, _ in frames), frames[-1][1]
        for secs, r in frames:
            if left < secs:
                rows = r
                break
            left -= secs
        ui.text(surf, "EXAMPLE", x, y, "dim")
        for i, pieces in enumerate(rows):
            ex = x
            for text, style in pieces:
                colour, bg = STYLES.get(style, (style, None))      # a hex view style, or a plain colour
                ex = ui.text(surf, text, ex, y + (i + 2) * ui.lh(), colour, bg=bg)


# ----------------------------------------------------------- shop / rest

class ShopScene(Scene):
    """Tools for credits. Opened from the map (B), the subnet's market keeps its
    stock between visits. It also opens with fresh stock when an IDS goes down,
    between one subnet and the next."""

    def __init__(self, game, run, seed=None):
        super().__init__(game)
        self.run = run
        self.market = run.market() if seed is None else {"stock": run.shop_stock(random.Random(seed), 3), "slot": 1}
        self.stock = self.market["stock"]
        self.msg = ("", "fg")
        self._build()

    def _build(self):
        run, items, self.actions = self.run, [], []
        self._god = run.god         # what could be afforded was worked out with god mode like this
        for d in self.stock:
            info = tools.TOOLS[d]
            items.append({"label": "BUY %-10s %4d cr" % (d, info.price), "desc": tools.describe(d),
                          "enabled": run.can_pay(info.price) and run.can_install()})
            self.actions.append(("buy", d))
        if self.market["slot"] and run.tool_slots < tools.MAX_SLOTS:
            items.append({"label": "BUY %-10s %4d cr" % ("+1 SLOT", tools.SLOT_PRICE),
                          "desc": "Run one more tool at a time (max %d)." % tools.MAX_SLOTS,
                          "enabled": run.can_pay(tools.SLOT_PRICE)})
            self.actions.append(("slot", None))
        for d in run.tools:
            items.append({"label": "SELL %-9s +%3d cr" % (d, tools.TOOLS[d].price // 2), "c": "dim"})
            self.actions.append(("sell", d))
        items.append({"label": "LEAVE"})
        self.actions.append(("leave", None))
        self.menu = ui.Menu(items, 80, 150, size=16, width=84)

    def handle_event(self, ev):
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            return self._leave()
        choice = self.menu.handle_event(ev)
        if choice is None:
            return
        run = self.run
        op, d = self.actions[choice]
        if op == "buy":
            run.pay(tools.TOOLS[d].price)
            run.install(d)
            self.stock.remove(d)
            self.msg = ("%s installed" % d, "tan")
            run.note("BLACK MARKET: bought %s for %d credits" % (d, tools.TOOLS[d].price), "fg")
        elif op == "slot":
            run.pay(tools.SLOT_PRICE)
            run.tool_slots += 1
            self.market["slot"] = 0
            self.msg = ("you can now run %d tools at a time" % run.tool_slots, "tan")
            run.note("BLACK MARKET: bought a tool slot for %d credits, %d slots now" % (tools.SLOT_PRICE, run.tool_slots),
                     "fg")
        elif op == "sell":
            run.tools.remove(d)
            run.credits += tools.TOOLS[d].price // 2
            self.msg = ("%s uninstalled" % d, "tan")
            run.note("BLACK MARKET: sold %s for %d credits" % (d, tools.TOOLS[d].price // 2), "fg")
        elif op == "leave":
            return self._leave()
        self._build()

    def crumbs(self):
        return run_crumbs(self.run, None, self._leave, "blackmarket")

    def _leave(self):
        self.game.pop()             # on to the next subnet's map

    def update(self, dt):
        self.run.tick(dt)
        if self.run.god != self._god:
            self._build()               # god mode switched while shopping: what can be afforded has changed
        if self.run.over:
            self.game.pop()             # traced while shopping: the map ends the run

    def draw(self, surf):
        run = self.run
        surf.fill(ui.BLACK)
        draw_header(self, surf, run)
        head = ("BLACK MARKET: tools and daemons for credits"
                if self.market is self.run.markets.get(self.run.level) else
                "BLACK MARKET: the IDS is down. Tools and daemons for credits, before you go deeper")
        ui.text(surf, head, 80, 84, "amber", 18)
        note = "Tool slots: %d of %d in use" % (len(run.tools), run.tool_slots)
        if not run.can_install():
            note += ". Full: sell a tool or buy a slot to install another."
        ui.text(surf, note, 80, 114, "dim")
        self.menu.draw(surf)
        ui.text(surf, self.msg[0], 80, self.menu.bottom + 10, self.msg[1])


class FootholdScene(Scene):
    def __init__(self, game, run, node):
        super().__init__(game)
        self.run, self.node = run, node
        self.menu = ui.Menu([
            {"label": "CLEAR LOGS", "desc": "Remove what the logs here say about you: TRACE -%d%%."
                                             % runmod.FOOTHOLD_TRACE},
            {"label": "MINE", "desc": "Run a miner here for a while: +%d credits." % runmod.FOOTHOLD_CREDITS},
        ], 80, 150, size=18, width=70)

    def crumbs(self):
        return run_crumbs(self.run, None, self.back_out, self.node.name, "foothold")

    def back_out(self):
        """Leave without resting: the node is still there to come back to."""
        self.run.back_out()
        self.game.pop()

    def handle_event(self, ev):
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            return self.back_out()
        choice = self.menu.handle_event(ev)
        if choice is None:
            return
        run = self.run
        if choice == 0:
            run.add_trace(-runmod.FOOTHOLD_TRACE)
            run.note("FOOTHOLD: logs cleared, TRACE -%d%%" % runmod.FOOTHOLD_TRACE, "fg")
        else:
            run.earn(runmod.FOOTHOLD_CREDITS)
            run.note("FOOTHOLD: mined %d credits" % runmod.FOOTHOLD_CREDITS, "fg")
        run.complete(self.node)
        self.game.pop()

    def update(self, dt):
        self.run.tick(dt)
        if self.run.over:
            self.game.pop()             # traced on the foothold: the map ends the run

    def draw(self, surf):
        surf.fill(ui.BLACK)
        draw_header(self, surf, self.run)
        ui.text(surf, "FOOTHOLD: a host nobody is watching", 80, 84, "amber", 18)
        self.menu.draw(surf)
        ui.text(surf, "ESC back to the map without using it", 80, ui.H - 30, "dim")


# ------------------------------------------------------------------- menu

# (keys, what they do); a row with no second part is a heading
KEYBINDS = [
    ("ANYWHERE", None),
    ("M", "this menu (not while a node's timer is running)"),
    ("L", "logs: what you have dissected so far"),
    ("ESC", "back one level"),
    ("click the path line", "back to that level"),
    ("drag across text", "highlight it; cmd+C copies it"),
    ("cmd+F, F11", "fullscreen on / off"),
    ("MENUS", None),
    ("arrows + ENTER", "choose an item"),
    ("a number key, or the mouse", "choose it straight away"),
    ("ON THE MAP", None),
    ("click, or a number", "move to a highlighted node"),
    ("arrows + SPACE", "pick a highlighted node, then move to it"),
    ("rest the mouse on a node", "see its briefing"),
    ("wheel, PgUp PgDn", "look back through the session log"),
    ("B", "the black market: buy tools and daemons"),
    ("ESC twice", "abandon the run"),
    ("IN A NODE", None),
    ("SPACE", "jack in; continue"),
    ("point at a byte", "the cursor marks it in both panes"),
    ("click", "pick a byte"),
    ("drag", "select a field (DISSECT); move a segment (REASSEMBLE)"),
    ("wheel, arrows, PgUp PgDn", "scroll a long dump"),
    ("0-9 a-f, BACKSPACE, ENTER", "type hex, or the bits of an XOR key byte"),
    ("1-9", "answer a CARVE question"),
    ("ENTER", "PAYLOAD: end the breach, upload what is in the buffer"),
    ("Q W R T Y", "use the tool in slot 1-5"),
    ("GOD MODE", None),
    ("click [GOD MODE]", "bottom right of any screen of a run: on / off"),
    ("while it is on", "credits never run out and TRACE never rises"),
    ("click any node on the map", "go straight to it; it still has to be solved"),
    ("click a SUBNET number", "on the map: go straight to that subnet"),
]


class MenuScene(Scene):
    """The popover on M: the keys, the glossary with its search box, and the
    way to the logs. It sits over the screen it was opened from, which stays
    drawn behind it but does not run."""
    menu_ok = False
    W, H = 880, 740             # the popover's size; it sits in the middle of whatever the screen is
    WIDTH = 80                  # characters across, inside the frame
    QUERY_MAX = 24

    X = property(lambda self: (ui.W - self.W) // 2)
    Y = property(lambda self: (ui.H - self.H) // 2)
    tx = property(lambda self: self.X + 3 * ui.cw())
    ty = property(lambda self: self.Y + 2 * ui.lh())

    def __init__(self, game):
        super().__init__(game)
        self.under = game.scene
        self.under.typing = None            # whatever was still typing behind is simply there
        self.page = "menu"                  # menu / keys / terms
        self.query, self.scroll = "", 0
        self.since = time.monotonic()       # for the search box's cursor
        self.rows = (self.H - 6 * ui.lh()) // ui.lh()       # lines of body text that fit
        self.menu = ui.Menu([
            {"label": "KEYS", "desc": "What every key does."},
            {"label": "TERMS", "desc": "Look up a word. Says which ones are real and which are this game's."},
            {"label": "LOGS", "desc": "Everything you have dissected so far."},
            {"label": self._fullscreen_label()},
        ], self.tx, self.ty + ui.lh(), size=16, width=self.WIDTH)

    def _fullscreen_label(self):
        return "FULLSCREEN: %s" % ("ON" if self.game.fullscreen else "OFF")

    def inside(self, pos):
        return self.X <= pos[0] < self.X + self.W and self.Y <= pos[1] < self.Y + self.H

    def _place(self):
        """Keep the item list where the frame is: the screen can change size under it.
        The fullscreen item's label follows the setting, switched here or with the hotkey."""
        self.menu.items[3]["label"] = self._fullscreen_label()
        if (self.menu.x, self.menu.y) != (self.tx, self.ty + ui.lh()):
            self.menu.x, self.menu.y = self.tx, self.ty + ui.lh()
            self.menu._layout()

    # ---- the glossary
    def term_lines(self):
        """The entries that match the search, as (text, colour) lines."""
        lines = []
        for term, text, real in glossary.search(self.query):
            lines.append((term + ("" if real else "   (this game's word, not a real term)"),
                          "amber" if real else "tan"))
            lines += [("  " + row, "fg") for row in ui.wrap(text, self.WIDTH - 4)]
            lines.append(("", "fg"))
        return lines

    def _scroll(self, by):
        self.scroll = max(0, min(max(0, len(self.term_lines()) - self.rows), self.scroll + by))

    # ---- input
    def handle_event(self, ev):
        self._place()
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and not self.inside(ev.pos):
            return self.game.pop()          # a click outside closes it
        if self.page == "menu":
            if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_ESCAPE, pygame.K_m):
                return self.game.pop()
            choice = self.menu.handle_event(ev)
            if choice == 2:
                return self.game.replace(LogsScene(self.game))
            if choice == 3:
                return self.game.set_fullscreen(not self.game.fullscreen)
            if choice is not None:
                self.page, self.query, self.scroll = ("keys", "terms")[choice], "", 0
        elif self.page == "keys":
            if ev.type == pygame.KEYDOWN and (ev.key in CONFIRM or ev.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE)):
                self.page = "menu"
        elif ev.type == pygame.MOUSEWHEEL:
            self._scroll(-int(getattr(ev, "precise_y", ev.y) * 2))
        elif ev.type == pygame.KEYDOWN:
            step = {pygame.K_UP: -1, pygame.K_DOWN: 1, pygame.K_PAGEUP: -self.rows, pygame.K_PAGEDOWN: self.rows}
            ch = ev.unicode or ""
            if ev.key == pygame.K_ESCAPE:
                self.page = "menu"
            elif ev.key in step:
                self._scroll(step[ev.key])
            elif ev.key == pygame.K_BACKSPACE:
                self.query, self.scroll = self.query[:-1], 0
            elif len(ch) == 1 and 32 <= ord(ch) < 127 and len(self.query) < self.QUERY_MAX:
                self.query, self.scroll = self.query + ch, 0        # every letter is typed, M and L included
            self.since = time.monotonic()

    # ---- drawing
    def draw(self, surf):
        self._place()
        frame = (self.X, self.Y, self.W, self.H)
        with ui.typewriter(None):           # the screen behind is already there; only the popover types
            self.under.draw(surf)
            surf.fill(ui.BLACK, ui.box(frame))
            ui.outline(surf, "fg", frame)
        ui.forget(frame)                    # what it covers can no longer be highlighted
        x, y, line = self.tx, self.ty, ui.lh()
        title = {"menu": "MENU", "keys": "MENU / KEYS", "terms": "MENU / TERMS"}[self.page]
        ui.text(surf, " %s " % title, self.X + 2 * ui.cw(), self.Y - line // 2, "amber", bg="bg")
        foot = self.Y + self.H - 2 * line
        if self.page == "menu":
            self.menu.draw(surf)
            ui.text(surf, "M or ESC close", x, foot, "dim")
        elif self.page == "keys":
            for keys, does in KEYBINDS:
                if does is None:
                    y += line // 2
                    ui.text(surf, keys, x, y, "amber")
                else:
                    ui.text(surf, "  %-27s %s" % (keys, does), x, y, "fg")
                y += line
            ui.text(surf, "ESC back", x, foot, "dim")
        else:
            lines = self.term_lines()
            found = len(glossary.search(self.query))
            end = ui.text(surf, "search > " + self.query, x, y, "tan")
            if ui.blink(self.since):
                ui.fill(surf, "tan", (end, y, ui.cw(), line))
            ui.text_right(surf, "%d of %d" % (found, len(glossary.TERMS)), self.X + self.W - 3 * ui.cw(), y, "dim")
            y += 2 * line
            if not lines:
                ui.text(surf, "nothing matches. BACKSPACE to widen the search.", x, y, "dim")
            for text, colour in lines[self.scroll:self.scroll + self.rows]:
                ui.text(surf, text, x, y, colour)
                y += line
            more = ("▲ " if self.scroll else "  ") + ("▼" if self.scroll + self.rows < len(lines) else " ")
            ui.text(surf, "type to search   arrows or wheel scroll   ESC back   %s" % more, x, foot, "dim")


# ------------------------------------------------------------------- logs

class LogsScene(Scene):
    def __init__(self, game):
        super().__init__(game)
        self.tabs = packets.LAYER_ORDER + ["FILES"]
        self.tab = 0
        self.tab_rects = []

    def root(self):
        return self.game.pop

    def crumbs(self):
        return [("logs", None), (self.tabs[self.tab].lower(), None)]

    def handle_event(self, ev):
        if ev.type == pygame.KEYDOWN:
            if ev.key in (pygame.K_ESCAPE, pygame.K_l) or ev.key in CONFIRM:
                return self.game.pop()
            if ev.key in (pygame.K_RIGHT, pygame.K_TAB, pygame.K_DOWN):
                self.tab = (self.tab + 1) % len(self.tabs)
            elif ev.key in (pygame.K_LEFT, pygame.K_UP):
                self.tab = (self.tab - 1) % len(self.tabs)
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            for i, rect in enumerate(self.tab_rects):
                if rect.collidepoint(ev.pos):
                    self.tab = i

    def draw(self, surf):
        surf.fill(ui.BLACK)
        save = self.game.save.data
        self.draw_path(surf)
        ui.text(surf, "LOGS", 40, 38, "amber", 18)
        x, self.tab_rects = 40, []
        for i, name in enumerate(self.tabs):
            label = " %s " % name.upper()
            if i == self.tab:
                ui.text(surf, label, x, 70, "bg", bg="tan")
            else:
                ui.text(surf, label, x, 70, "fg")
            self.tab_rects.append(pygame.Rect(x, 70, len(label) * ui.cw(), ui.lh()))
            x += (len(label) + 1) * ui.cw()
        y, line = 106, ui.lh()
        name = self.tabs[self.tab]
        if name == "FILES":
            ui.text(surf, "File signatures (magic numbers) recovered in CARVE nodes.", 40, y, "dim")
            y += 2 * line
            for sig, (magic, _, desc, _) in SIGNATURES.items():
                if sig in save["signatures"]:
                    ui.text(surf, "%-7s %-26s %s" % (sig, puzzles.base.hexs(magic), desc), 40, y, "fg")
                else:
                    ui.text(surf, "%-7s %s" % ("?" * len(sig), "-- not recovered yet --"), 40, y, "dim")
                y += line
            # the formats CARVE never asks about, because their signature prints their name
            ui.text(surf, "Some formats name themselves in the ASCII pane and need no carving practice:", 40, y + line, "dim")
            ui.text(surf, "   ".join(puzzles.base.printable(s.encode("latin-1")) for s in puzzles.SELF_NAMING),
                    40, y + 2 * line, "fg")
            return
        ui.text(surf, packets.LAYER_NOTES[name], 40, y, "dim")
        y += 2 * line
        ui.text(surf, "offset size  field", 40, y, "amber")
        y += line
        for field, (layer, label, desc) in packets.FIELD_INFO.items():
            if layer != name:
                continue
            off, size = packets.FIELD_LAYOUT[field]
            where = "+0x%02X" % off if off is not None else "  var"
            span = "%4d" % size if size is not None else " var"
            entry = save["manual"].get(field)
            if entry:
                ui.text(surf, "%s  %s  %-26s e.g. %s" % (where, span, label, entry["example"][:60]), 40, y, "fg")
                ui.text(surf, desc, 40 + 13 * ui.cw(), y + line, "dim")
            else:
                ui.text(surf, "%s  %s  %s" % (where, span, "-- not dissected yet --"), 40, y, "dim")
            y += 2 * line if entry else line


# -------------------------------------------------------------- game over

def end_run(game, run):
    """Straight to the end-of-run report, from wherever the run ended."""
    del game.stack[1:]
    game.push(GameOverScene(game, run))


class GameOverScene(Scene):
    """The end-of-run report. It is typed out, stays up while a countdown
    runs, then the line drops: the screen goes dark and the title boots."""
    TYPE_CPS = 240          # characters a second while the report types out
    TYPE_MAX = 3.0
    HOLD = 15.0             # seconds before you are disconnected
    DARK = 1.2              # seconds of black screen before the title comes back
    GRACE = 0.4             # ignore input this long, so the key that ended the run does not skip the report

    def __init__(self, game, run):
        super().__init__(game)
        self.run = run
        self.won = run.over == "won"
        # a run that had god mode on was for trying things out: it stays out of the records
        self.best = False if run.god_used else game.save.record_run(
            run.mode, run.level if not self.won else runmod.SUBNETS, self.won, run.elapsed)
        game.save.write()
        self.t = 0.0
        self.dark = None        # seconds of blackout so far, once disconnected

    @property
    def menu_ok(self):
        return self.dark is None

    def crumbs(self):
        return run_crumbs(self.run)

    def skip_typing(self):
        """The first press only finishes the typing; it takes another to disconnect."""
        if self.t >= self.GRACE:
            self.typing = None
        return True

    def handle_event(self, ev):
        if is_press(ev) and self.dark is None and self.t >= self.GRACE:
            self.dark = 0.0     # disconnect now

    def update(self, dt):
        if self.dark is not None:
            self.dark += dt
            if self.dark >= self.DARK:
                self.game.pop()
                if isinstance(self.game.scene, TitleScene):
                    self.game.scene.boot()
            return
        self.t += dt
        if self.t >= self.HOLD:
            self.dark = 0.0

    def draw(self, surf):
        surf.fill(ui.BLACK)
        if self.dark is not None:
            return
        run, st = self.run, self.run.stats
        self.draw_path(surf)
        if self.won:
            ui.text(surf, "ALL FIVE SUBNETS BREACHED", 80, 90, "amber", 20)
            ui.text(surf, "you were never here.", 80, 124, "fg")
        else:
            ui.text(surf, "CONNECTION TERMINATED", 80, 90, "red", 20)
            why = "you pulled the plug in subnet %d." if run.abandoned else "you have been traced in subnet %d."
            ui.text(surf, why % run.level, 80, 124, "fg")
        rows = [
            "mode            %s" % run.mode,
            "time            %s%s" % (ui.clock(run.elapsed), "   NEW BEST" if self.best else ""),
            "subnet reached  %d/%d" % (run.level, runmod.SUBNETS),
            "nodes solved    %d" % st["solved"],
            "timeouts        %d" % st["failed"],
            "mistakes        %d" % st["mistakes"],
            "IDS evaded      %d" % st["ids"],
            "credits earned  %d" % st["credits"],
        ]
        if run.god_used:
            rows.append("god mode        on: this run is not counted in the records")
        y = 180
        for row in rows:
            ui.text(surf, row, 80, y, "fg")
            y += ui.lh()
        y += ui.lh()
        if run.new_unlocks:
            ui.text(surf, "TOOLS UNLOCKED FOR FUTURE RUNS", 80, y, "amber")
            y += ui.lh()
            for d in run.new_unlocks:
                ui.text(surf, "  %-10s %s" % (d, tools.TOOLS[d].desc), 80, y, "tan")
                y += ui.lh()
            y += ui.lh()
        if run.new_fields:
            ui.text(surf, "NEW LOG ENTRIES: %d" % len(run.new_fields), 80, y, "amber")
            y += ui.lh()
            for row in ui.wrap(", ".join(run.new_fields), 110)[:8]:
                ui.text(surf, "  " + row, 80, y, "fg")
                y += ui.lh()
        left = max(0, math.ceil(self.HOLD - self.t))
        ui.text(surf, "disconnecting in %ds" % left, 80, ui.H - 40, "red" if left <= 5 else "amber")
        ui.text(surf, "[SPACE] disconnect now", 80 + 26 * ui.cw(), ui.H - 40, "tan")
