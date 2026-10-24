"""The hex-dump widget:  offset | hex bytes (16 a row unless told otherwise) | ASCII.

The byte under the mouse gets a blinking block cursor in both panes at once,
the way Wireshark's packet bytes pane links them. Click for single bytes,
drag for ranges, or (in "move" mode) drag bytes from one place to another. The owner hands it the
bytes and a style per byte index every frame; the view owns only hover,
drag-selection, scrolling and the IDS display effects.
"""
import random
import time

import pygame

import ui
from puzzles.base import printable

COLS = 16                   # bytes a row, unless the puzzle asks for another width

# style -> (text colour, background or None)
STYLES = {
    None: ("fg", None),
    "zero": ("dim", None),
    "dim": ("dim", None),
    "hint": ("amber", ui.TINT),
    "band": ("amber", None),
    "active": ("fg", ui.TINT),
    "sel": ("bg", "tan"),
    "found": ("bg", "fg"),
    "picked": ("bg", "amber"),
    "flash": ("bg", "amber"),
    "bad": ("bg", "red"),
    "empty": ("dim", None),     # a byte still to fill in: shown __
    "void": ("dim", None),      # no byte here at all: nothing is drawn
}
# styles that stay readable under the DARK modifier
STICKY = {"sel", "found", "picked", "flash"}
# IDS LOSS: this share of the bytes never arrived (shown ??); every few seconds
# one is resent and another is dropped. THROTTLE: rows of the dump arriving per second.
LOSS_SHARE = 0.04
LOSS_RESEND = 3.0
THROTTLE_ROWS = 3


class HexView:
    def __init__(self, x, y, rows=24, size=18):
        self.x, self.y, self.rows, self.size = x, y, rows, size
        self.cw, self.lh = ui.cw(size), ui.lh(size)
        self.x_hex = x + 6 * self.cw
        self.cols = COLS
        self.height = (rows + 1) * self.lh
        self.data = b""
        self.styles = {}
        self.bands = []             # (name, start, end) header boundaries, drawn when set
        self.select_mode = "click"
        self.scroll = 0
        self.hover = None
        self._moved = 0.0           # when the hover last changed: restarts the cursor blink
        self.sel = None             # (lo, hi) while dragging
        self._anchor = None
        self._wheel = 0.0
        # IDS effects
        self.hide_ascii = False
        self.codepage = False       # the CODEPAGE tool: a symbol for every byte in the ASCII pane, not a dot
        self.hide_offsets = False
        self.dark = False
        self.loss = False           # some bytes never arrived
        self.throttle = False       # the dump arrives a few rows a second
        self._fx = random.Random()
        self._fx_clock = 0.0
        self._lost = set()
        self._loaded = 0.0          # bytes arrived so far, under throttle

    # ---- geometry
    @property
    def cols(self):
        return self._cols

    @cols.setter
    def cols(self, n):
        self._cols = n
        self.half = n // 2          # the gap between the two halves of a row comes after this many
        self.x_ascii = self.x_hex + (n * 3 + 3) * self.cw
        self.width = self.x_ascii + n * self.cw - self.x

    def _col_x(self, col):
        return self.x_hex + (col * 3 + (1 if col >= self.half else 0)) * self.cw

    def max_scroll(self):
        total = (len(self.data) + self.cols - 1) // self.cols
        return max(0, total - self.rows)

    def scroll_by(self, rows):
        self.scroll = max(0, min(self.max_scroll(), self.scroll + rows))

    def is_visible(self, idx):
        return self.scroll <= idx // self.cols < self.scroll + self.rows

    def ensure_visible(self, idx):
        row = idx // self.cols
        if row < self.scroll:
            self.scroll = row
        elif row >= self.scroll + self.rows:
            self.scroll = row - self.rows + 1

    def byte_rect(self, idx, pane="hex"):
        row, col = idx // self.cols - self.scroll, idx % self.cols
        y = self.y + (row + 1) * self.lh
        if pane == "hex":
            return pygame.Rect(self._col_x(col), y, 2 * self.cw, self.lh)
        return pygame.Rect(self.x_ascii + col * self.cw, y, self.cw, self.lh)

    def index_at(self, pos):
        """Byte index under a pixel position in either pane, or None."""
        px, py = pos
        row = (py - self.y) // self.lh - 1
        if not 0 <= row < self.rows:
            return None
        col = None
        if self.x_hex <= px < self.x_hex + (self.cols * 3 + 1) * self.cw:
            chars = (px - self.x_hex) // self.cw
            if chars < self.half * 3:
                col = chars // 3
            elif chars >= self.half * 3 + 1:
                col = self.half + (chars - self.half * 3 - 1) // 3
        elif self.x_ascii <= px < self.x_ascii + self.cols * self.cw and not self.hide_ascii:
            col = (px - self.x_ascii) // self.cw
        if col is None or col >= self.cols:
            return None
        idx = (self.scroll + row) * self.cols + col
        return idx if idx < len(self.data) else None

    def contains(self, pos):
        return self.x <= pos[0] < self.x + self.width and self.y <= pos[1] < self.y + self.height

    # ---- input
    def handle_event(self, ev):
        """Returns a list of ("click", idx) / ("select", lo, hi) / ("move", src, dst or None)."""
        out, before = [], self.hover
        if ev.type == pygame.MOUSEMOTION:
            self.hover = self.index_at(ev.pos)
            if self._anchor is not None and self.hover is not None and self.select_mode == "drag":
                self.sel = (min(self._anchor, self.hover), max(self._anchor, self.hover))
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            idx = self.index_at(ev.pos)
            if idx is not None:
                self.hover = idx
                if self.select_mode == "click":
                    out.append(("click", idx))
                elif self.select_mode == "move":
                    self._anchor = idx
                else:
                    self._anchor, self.sel = idx, (idx, idx)
        elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
            if self._anchor is not None and self.select_mode == "move":
                out.append(("move", self._anchor, self.index_at(ev.pos)))
                self._anchor = None
            elif self._anchor is not None:
                idx = self.index_at(ev.pos)
                if idx is not None:
                    self.sel = (min(self._anchor, idx), max(self._anchor, idx))
                out.append(("select",) + self.sel)
                self._anchor, self.sel = None, None
        elif ev.type == pygame.MOUSEWHEEL:
            # trackpads send many small fractional steps: accumulate them
            self._wheel += getattr(ev, "precise_y", ev.y) * 2
            rows = int(self._wheel)
            self._wheel -= rows
            self.scroll_by(-rows)
        elif ev.type == pygame.KEYDOWN:
            step = {pygame.K_UP: -1, pygame.K_DOWN: 1, pygame.K_PAGEUP: -self.rows,
                    pygame.K_PAGEDOWN: self.rows}.get(ev.key)
            if step:
                self.scroll_by(step)
        if self.hover != before:
            self._moved = time.monotonic()
        return out

    @property
    def dragging(self):
        """In "move" mode, while the button is down: (byte picked up, byte under the mouse or None)."""
        return (self._anchor, self.hover) if self._anchor is not None and self.select_mode == "move" else None

    def cursor(self):
        """The byte the block cursor is on right now: the hovered byte, while
        the blink is lit, and never during a drag."""
        return self.hover if self._anchor is None and ui.blink(self._moved) else None

    def reset(self):
        self.scroll, self.hover, self.sel, self._anchor = 0, None, None, None
        self._lost, self._loaded = set(), 0.0

    # ---- effects (IDS modifiers only). Both are things a real network does:
    # dropped packets and a rate limit. Nothing shakes or flickers.
    def update(self, dt):
        n = len(self.data)
        self._loaded += dt * THROTTLE_ROWS * self.cols
        if not self.loss or not n:
            self._lost = set()
            return
        if not self._lost:
            self._lost = set(self._fx.sample(range(n), max(1, round(n * LOSS_SHARE))))
            self._fx_clock = LOSS_RESEND
        self._fx_clock -= dt
        if self._fx_clock <= 0:
            # one lost byte is resent and arrives; another goes missing
            self._fx_clock = LOSS_RESEND
            self._lost.discard(self._fx.choice(sorted(self._lost)))
            self._lost.add(self._fx.randrange(n))

    # ---- drawing
    def _style(self, idx):
        if self.sel is not None and self.sel[0] <= idx <= self.sel[1]:
            return "sel"
        return self.styles.get(idx)

    def _lit(self, idx):
        """Under DARK, is this byte inside the pool of light around the cursor?"""
        if self.hover is None:
            return False
        c = self.cols
        return abs(idx // c - self.hover // c) <= 1 and abs(idx % c - self.hover % c) <= 3

    def draw(self, surf):
        cw, lh, size = self.cw, self.lh, self.size
        data, n = self.data, len(self.data)
        band_of = {}
        for b, (_, start, end) in enumerate(self.bands):
            for i in range(start, min(end, n)):
                band_of[i] = b
        header = "".join("%02X " % c + (" " if c == self.half - 1 else "") for c in range(self.cols))
        ui.text(surf, header, self.x_hex, self.y, "dim", size)
        cursor = self.cursor()

        for r in range(self.rows):
            base = (self.scroll + r) * self.cols
            if base >= n:
                break
            y = self.y + (r + 1) * lh
            offset = "····" if self.hide_offsets else "%04X" % base
            ui.text(surf, offset, self.x, y, "dim", size)
            for col in range(self.cols):
                idx = base + col
                if idx >= n:
                    break
                style = self._style(idx)
                if style == "void":
                    continue
                value = data[idx]
                hidden = self.dark and style not in STICKY and not self._lit(idx)
                if self.throttle and idx >= self._loaded:
                    fg, bg, hx, ch = "dim", None, "  ", " "
                elif idx in self._lost:
                    fg, bg = STYLES["sel"] if idx == cursor else ("dim", None)
                    hx, ch = "??", "?"
                elif idx == cursor:
                    fg, bg = STYLES["sel"]
                    hx = "%02X" % value
                    ch = printable([value], self.codepage)
                elif hidden:
                    fg, bg, hx, ch = "dim", None, "··", "·"
                elif style == "empty":
                    fg, bg, hx, ch = "dim", None, "__", "_"
                else:
                    if style is None:
                        if band_of.get(idx, 0) % 2:
                            style = "band"
                        elif value == 0:
                            style = "zero"
                    fg, bg = STYLES[style]
                    hx = "%02X" % value
                    ch = printable([value], self.codepage)
                x = self._col_x(col)
                if bg is not None:
                    # run the highlight through the gap when the next byte shares it
                    wide = 2 * cw
                    if (col < self.cols - 1 and idx + 1 < n and cursor not in (idx, idx + 1)
                            and STYLES[self._style(idx + 1)][1] == bg):
                        wide = self._col_x(col + 1) - self._col_x(col)
                    ui.fill(surf, bg, (x, y, wide, lh))
                ui.text(surf, hx, x, y, fg, size)
                if not self.hide_ascii:
                    ax = self.x_ascii + col * cw
                    if bg is not None:
                        ui.fill(surf, bg, (ax, y, cw, lh))
                    # a dot standing in for an unprintable byte is dim; a real full stop is not
                    ui.text(surf, ch, ax, y, fg if bg or self.codepage or 32 <= value < 127 else "dim", size)
        if self.hide_ascii and n:
            # the IDS has taken the ASCII pane: say so where it would be
            ui.text(surf, "IDS BLACKOUT", self.x_ascii, self.y + lh, "red", size)

        # header boundaries: a tick at the first byte of each layer
        for b, (name, start, end) in enumerate(self.bands):
            if self.is_visible(start) and start < n:
                r = self.byte_rect(start)
                ui.fill(surf, "tan", (r.x - 4, r.y + 2, 2, r.height - 4))

        if self.max_scroll():
            first = self.scroll * self.cols
            last = min(n, first + self.rows * self.cols) - 1
            more = ("▲ " if self.scroll else "  ") + ("▼" if self.scroll < self.max_scroll() else " ")
            ui.text(surf, "%s showing 0x%04X-0x%04X of 0x%04X  (scroll)" % (more, first, last, n - 1),
                    self.x, self.y + (self.rows + 1) * lh + 4, "dim", 14)
