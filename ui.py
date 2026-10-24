"""Text drawing, log panel, bars and menus. Everything on screen is monospace
text; there are no images.

The game is laid out on a grid of units, and every coordinate anywhere in it
is in those units. The view maps units to real pixels: 2 pixels per unit in a
window on a Retina display, whatever fits in fullscreen. The grid is W x H
units, never less than BASE_W x BASE_H: a surface of another shape gets a
wider or a taller grid, so the layout always reaches all four corners, the way
a terminal has more columns in a wider window. Lay out from the top left, and
place what belongs on the right or at the bottom from W and H. Text is
rendered at the pixel size, never scaled up, so it stays sharp. Draw only
through this module (text, fill, outline) so the view is applied.
"""
import collections
import math
import os
import textwrap
import time

import pygame
import pygame.freetype

BASE_W, BASE_H = 1280, 800  # the smallest the layout gets, and the window's size to begin with
W, H = BASE_W, BASE_H       # the layout as it is now: set_view grows it to fill the surface

BLACK = (0, 0, 0)
GREEN = (57, 255, 106)
DIM = (26, 122, 58)
AMBER = (255, 176, 0)
TAN = (214, 186, 132)       # selection highlight, after Wireshark's byte pane
RED = (255, 64, 64)
TINT = (0, 46, 20)          # faint green wash behind "live" bytes
MARK = (196, 210, 202)      # text highlighted by dragging the mouse over it, as in a terminal

COLORS = {"fg": GREEN, "dim": DIM, "amber": AMBER, "tan": TAN, "red": RED, "bg": BLACK, "mark": MARK}

FONT_FILES = ["/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Monaco.ttf"]
FALLBACK_NAMES = "menlo,dejavusansmono,liberationmono,consolas,couriernew,courier"
CAPS = "BDEFHIKLMNPRTUVWXYZ"        # the capitals with flat tops: all exactly as tall as one another
# Text is drawn a little heavier than the font's own outlines, the way macOS
# draws it, so it looks as it does in a terminal or a browser. Drawn as the
# outlines stand, light text on black comes out thin, and thin reads as soft.
# The extra stroke width, in pixels: WEIGHT[0], plus WEIGHT[1] for every pixel
# of the font's size. (0, 0) draws the outlines as they are.
WEIGHT = (0.4, 0.008)
BLEED = 2                           # spare pixels either side of a glyph, so the extra weight is never cut off

# Box-drawing characters, indexed by which arms they have (N=1 E=2 S=4 W=8).
# They are drawn as shapes rather than taken from the font, so the lines of
# the map join up exactly at any scale.
BOX = " ╵╶└╷│┌├╴┘─┴┐┤┬┼"
DRAWN = set(BOX[1:])
CACHE_BYTES = 96 << 20      # rendered text kept before the cache is dropped

BLINK = 0.53                # seconds per half of a cursor blink

# ---- the view: layout units -> pixels on the real surface
SCALE = 1.0                 # pixels per unit
_points = 1.0               # window coordinates (what mouse events carry) per unit

# ---- typing a screen out
_typing = None              # characters still to be drawn this frame; None = no limit
_cut = False                # something was held back
_asked = 0                  # running count of characters asked for while a limit was on

# ---- what is on screen: every piece of text drawn this frame, as (x, y, string, size).
# Dragging the mouse highlights text the way a terminal does, and this is what it highlights.
runs = []

_files = {}                 # pixel size -> Font: what text is measured with
_inks = {}                  # pixel size -> the same font as a freetype Font: what its glyphs are drawn with
_path = None                # the font file in use
_draw_fonts = {}            # layout size -> (Font to draw with, True if its glyphs fill the cell exactly)
_glyphs = {}
_cache = {}
_cache_size = 0


def _px(v):
    return math.floor(v * SCALE + 0.5)


def set_view(pixels, window=None):
    """Fit the layout to a surface of the given pixel size. The base grid is
    scaled as large as it will go, and the layout then grows whichever way the
    surface has room to spare, so it fills the surface corner to corner at any
    shape. window is the window's size in its own coordinates, which is not
    its pixel size on a high-DPI display."""
    global SCALE, W, H, _points, _cache_size
    wide, high = pixels
    if wide * BASE_H <= high * BASE_W:      # the width sets the scale: any room to spare is below
        scale, size = wide / BASE_W, (BASE_W, high * BASE_W // wide)
    else:                                   # the height does: the room is to the right
        scale, size = high / BASE_H, (wide * BASE_H // high, BASE_H)
    if scale != SCALE:
        _draw_fonts.clear()
        _glyphs.clear()
        _cache.clear()
        _cache_size = 0
    SCALE = scale
    W, H = size
    _points = scale * (window or pixels)[0] / wide


def to_layout(pos):
    """Window coordinates (a mouse event's pos) -> layout units."""
    return round(pos[0] / _points), round(pos[1] / _points)


def to_window(pos):
    return round(pos[0] * _points), round(pos[1] * _points)


def X(x):
    return _px(x)


def Y(y):
    return _px(y)


def box(rect):
    """A rect in units -> the pixels it covers. Neighbouring rects never leave a gap."""
    x, y, w, h = rect
    return X(x), Y(y), X(x + w) - X(x), Y(y + h) - Y(y)


def color(c):
    return COLORS[c] if isinstance(c, str) else c


def fill(surf, c, rect):
    if _typing is None or _typing > 0:
        surf.fill(color(c), box(rect))


def outline(surf, c, rect, width=1):
    if _typing is None or _typing > 0:
        pygame.draw.rect(surf, color(c), box(rect), max(1, _px(width)))


class typewriter:
    """A screen being typed out. Inside the block only the first `count`
    characters of text appear, in the order they are drawn, with a block
    cursor after the last. .done says whether everything fitted. A count of
    None draws the lot."""

    def __init__(self, count):
        self.count, self.done = count, True
        self.total = 0                          # characters the block asked for, shown or not

    def __enter__(self):
        global _typing, _cut
        self._outer = (_typing, _cut)           # blocks nest: a popover draws the screen under it in full
        self._before = _asked
        _typing, _cut = (None if self.count is None else max(0, self.count)), False
        return self

    def __exit__(self, *exc):
        global _typing, _cut, _asked
        self.done, self.total = not _cut, _asked - self._before
        _typing, _cut = self._outer


# ---- fonts

def _file(px):
    global _path
    f = _files.get(px)
    if f is None:
        for path in FONT_FILES:
            try:
                f = pygame.font.Font(path, px)
                break
            except (OSError, pygame.error):
                continue
        else:
            path = pygame.font.match_font(FALLBACK_NAMES)
            f = pygame.font.Font(path, px)
        _files[px], _path = f, path
    return f


def _ink(px):
    """The font of _file(px), set up to draw its glyphs at WEIGHT."""
    f = _inks.get(px)
    if f is None:
        _file(px)                   # settles which font file is in use
        if not pygame.freetype.get_init():
            pygame.freetype.init()
        f = _inks[px] = pygame.freetype.Font(_path, px)
        f.strength = (WEIGHT[0] + WEIGHT[1] * px) / px      # as a share of the font's size
    return f


def font(size=16):
    """The font the layout is measured in: one unit per pixel."""
    return _file(size)


def cw(size=16):
    return font(size).size("0")[0]


def lh(size=16):
    return font(size).get_linesize()


def _level(f):
    """False at the pixel sizes where the font's own hinting draws some
    capitals a pixel taller than the rest (Menlo at 32px: B, E and F), which
    shows in a word like TRACE."""
    return len({top for _, _, _, top, _ in f.metrics(CAPS)}) == 1


def _draw_font(size):
    """The font actually drawn with: the largest whose characters fit the
    scaled cell, so text is rendered at the pixel size rather than stretched.
    A size that draws its capitals unevenly is passed over for the next one down."""
    found = _draw_fonts.get(size)
    if found is None:
        if SCALE == 1:
            found = (font(size), True)
        else:
            cell, row = cw(size) * SCALE, lh(size) * SCALE
            smallest = max(4, int(size * SCALE) - 4)
            best = _file(smallest)
            for px in range(smallest + 1, int(size * SCALE) + 6):
                f = _file(px)
                if f.size("0")[0] <= cell + 1e-6 and f.get_linesize() <= row + 1 and _level(f):
                    best = f
            found = (best, best.size("0")[0] == cell)
        _draw_fonts[size] = found
    return found


def _glyph(ch, c, size, f):
    """One character on its cell: as wide as its advance (and BLEED more
    either side), as high as the font, its baseline at the font's ascent."""
    key = (ch, c, size)
    g = _glyphs.get(key)
    if g is None:
        wide, high = f.size(ch)
        g = _glyphs[key] = pygame.Surface((wide + 2 * BLEED, high), pygame.SRCALPHA)
        heavy = pygame.freetype.STYLE_STRONG if any(WEIGHT) else pygame.freetype.STYLE_NORMAL
        ink, rect = _ink(f.point_size).render(ch, color(c), style=heavy)
        g.blit(ink, (BLEED + rect.x, f.get_ascent() - rect.y))      # rect: where the ink sits from the pen
    return g


def _compose(s, c, size, f):
    """Build a string one cell at a time: font glyphs on the scaled grid,
    box-drawing characters as shapes that fill their cell."""
    cell, col = cw(size) * SCALE, color(c)
    high = max(math.ceil(lh(size) * SCALE), f.get_linesize())
    img = pygame.Surface((max(1, _px(len(s) * cw(size))), high), pygame.SRCALPHA)
    top = (high - f.get_linesize()) // 2
    stroke = max(1, round(size * SCALE / 14))
    for i, ch in enumerate(s):
        x, wide = _px(i * cw(size)), _px((i + 1) * cw(size)) - _px(i * cw(size))
        if ch == " ":
            continue
        if ch in DRAWN:
            arms = BOX.index(ch)
            sx, sy = (wide - stroke) // 2, (high - stroke) // 2
            for bit, rect in ((1, (x + sx, 0, stroke, sy + stroke)), (4, (x + sx, sy, stroke, high - sy)),
                              (8, (x, sy, sx + stroke, stroke)), (2, (x + sx, sy, wide - sx, stroke))):
                if arms & bit:
                    img.fill(col, rect)
        else:
            img.blit(_glyph(ch, c, size, f), (x - BLEED, top))
    return img


def render(s, c="fg", size=16):
    """A string as a surface, at the view's pixel size."""
    global _cache_size
    key = (s, c, size)
    surf = _cache.get(key)
    if surf is None:
        if len(_cache) > 6000 or _cache_size > CACHE_BYTES:
            _cache.clear()
            _cache_size = 0
        surf = _compose(s, c, size, _draw_font(size)[0])
        _cache[key] = surf
        _cache_size += surf.get_width() * surf.get_height() * 4
    return surf


def text(surf, s, x, y, c="fg", size=16, bg=None):
    """Draw a string. Returns the x just past it."""
    global _typing, _cut, _asked
    if not s:
        return x
    end = x + len(s) * cw(size)
    if _typing is not None:
        _asked += len(s)
        if len(s) > _typing:
            s, _cut = s[:_typing], True
            if not s:
                return end
        _typing -= len(s)
    runs.append((x, y, s, size))
    _blit(surf, s, x, y, c, size, bg)
    if _typing == 0:        # the typing has got this far: leave the cursor here
        surf.fill(TAN, box((x + len(s) * cw(size), y, cw(size), lh(size))))
    return end


def _blit(surf, s, x, y, c, size, bg=None):
    img = render(s, c, size)
    if bg is not None:
        surf.fill(color(bg), box((x, y, len(s) * cw(size), lh(size))))
    row = Y(y + lh(size)) - Y(y)
    surf.blit(img, (X(x), Y(y) + (row - img.get_height()) // 2))


# ---- highlighting text by dragging over it

def begin_frame():
    """Forget last frame's text. Call before a screen is drawn."""
    del runs[:]


def forget(rect):
    """Drop the text recorded inside rect: it has been painted over (by a
    popover). A line that runs through the rect keeps the parts either side."""
    left, top, wide, high = rect
    kept = []
    for x, y, s, size in runs:
        w = cw(size)
        if not (top - lh(size) < y < top + high) or x >= left + wide or x + len(s) * w <= left:
            kept.append((x, y, s, size))
            continue
        before = max(0, -(-(left - x) // w))            # characters that end at or before the rect
        after = max(0, -(-(left + wide - x) // w))      # first character that starts at or past it
        if before:
            kept.append((x, y, s[:before], size))
        if after < len(s):
            kept.append((x + after * w, y, s[after:], size))
    runs[:] = kept


def marked(a, b):
    """The text a drag from point a to point b covers, the way a terminal
    selects: from the first point to the end of its line, every line in
    between, and the last line up to the second point.
    Returns pieces as (x, y, string, size)."""
    if (b[1], b[0]) < (a[1], a[0]):
        a, b = b, a
    out = []
    for x, y, s, size in runs:
        w, h = cw(size), lh(size)
        first, last = y <= a[1] < y + h, y <= b[1] < y + h
        lo, hi = 0, len(s) - 1
        if first and last:
            lo, hi = sorted(((a[0] - x) // w, (b[0] - x) // w))
        elif first:
            lo = (a[0] - x) // w
        elif last:
            hi = (b[0] - x) // w
        elif not a[1] < y < b[1]:
            continue
        lo, hi = max(0, int(lo)), min(len(s) - 1, int(hi))
        if lo <= hi:
            out.append((x + lo * w, y, s[lo:hi + 1], size))
    return out


def draw_marked(surf, a, b):
    for x, y, s, size in marked(a, b):
        _blit(surf, s, x, y, "bg", size, bg="mark")


def marked_text(a, b):
    """The highlighted text as plain lines, top to bottom, laid out by column."""
    lines = {}
    for x, y, s, size in marked(a, b):
        row = lines.setdefault(y, {})
        for i, ch in enumerate(s):
            row[x + i * cw(size)] = (ch, cw(size))      # drawn twice at one spot: the later one shows
    out = []
    for y in sorted(lines):
        text, at = "", None
        for x in sorted(lines[y]):
            ch, w = lines[y][x]
            if at is not None and x > at:
                text += " " * max(0, round((x - at) / w))
            text, at = text + ch, x + w
        out.append(text.rstrip())
    return "\n".join(out)


def blink(since=0.0):
    """Terminal-cursor blink: True for the lit half of each cycle. since is
    when the cursor last moved (time.monotonic()), so it is lit straight after."""
    return int((time.monotonic() - since) / BLINK) % 2 == 0


def text_right(surf, s, right, y, c="fg", size=16):
    text(surf, s, right - len(s) * cw(size), y, c, size)


def text_center(surf, s, cx, y, c="fg", size=16):
    text(surf, s, cx - len(s) * cw(size) // 2, y, c, size)


def bar(frac, width):
    """A meter the way a terminal draws one: [|||||||     ]"""
    n = int(round(max(0.0, min(1.0, frac)) * width))
    return "[%s%s]" % ("|" * n, " " * (width - n))


def pct(amount):
    """A TRACE amount for display: whole numbers plain, anything else to one decimal."""
    return "%d" % amount if amount == int(amount) else "%.1f" % amount


def wrap(s, width):
    return textwrap.wrap(s, width) or [""]


def fit_path(path, width):
    """A path cut to width characters, keeping its end: the home directory
    becomes ~ first, then the front goes."""
    home = os.path.expanduser("~")
    if len(path) > width and path.startswith(home + os.sep):
        path = "~" + path[len(home):]
    return path if len(path) <= width else "\u2026" + path[len(path) - width + 1:]


def trace_color(trace):
    return "red" if trace >= 80 else "amber" if trace >= 50 else "fg"


def clock(seconds):
    seconds = int(seconds)
    return "%d:%02d" % (seconds // 60, seconds % 60)


class Log:
    """Scrolling message log; newest line at the bottom. A line too long for
    the panel wraps, and scroll_by looks back through the older ones."""

    def __init__(self, keep=200, echo=None):
        self.lines = collections.deque(maxlen=keep)
        self.counts = collections.deque(maxlen=keep)    # how many times running each line was added
        self.echo = echo            # called with every line added: how a node's log reaches the run's
        self.scroll = 0             # rows back from the newest; 0 shows the latest
        self._rows = (None, [])     # (width, the lines wrapped to it)

    def add(self, s, c="fg"):
        if self.lines and self.lines[-1] == (s, c):     # the same thing twice in a row is one line, counted
            self.counts[-1] += 1
        else:
            self.lines.append((s, c))
            self.counts.append(1)
        self.scroll, self._rows = 0, (None, [])         # something new: back to the latest
        if self.echo is not None:
            self.echo(s, c)

    def rows(self, width=80):
        """The log as it is drawn: one (text, colour) per row on screen."""
        if self._rows[0] != width:
            out = []
            for (s, c), n in zip(self.lines, self.counts):
                first, *rest = wrap(s + ("  (x%d)" % n if n > 1 else ""), width - 2)
                out.append(("> " + first, c))
                out.extend(("  " + more, c) for more in rest)
            self._rows = (width, out)
        return self._rows[1]

    def scroll_by(self, by, rows, width=80):
        """Look back by this many rows (forward if negative) in a panel of the given size."""
        self.scroll = max(0, min(len(self.rows(width)) - rows, self.scroll + by))

    def draw(self, surf, x, y, rows, size=16, width=80):
        every = self.rows(width)
        end = len(every) - self.scroll
        for i, (s, c) in enumerate(every[max(0, end - rows):end]):
            text(surf, s, x, y + i * lh(size), c, size)


class Menu:
    """Vertical list driven by arrows + ENTER, number keys, or the mouse.
    Items are dicts: label, desc (optional), enabled (default True), c (colour),
    key (what shows in the brackets; the item's number unless given, and a
    named key is not chosen by a number). gap is the space between items, in lines."""

    def __init__(self, items, x, y, size=16, width=70, gap=0.5):
        self.items = items
        self.x, self.y, self.size, self.width, self.gap = x, y, size, width, gap
        self.index = next((i for i, it in enumerate(items) if it.get("enabled", True)), 0)
        self._lit = (None, 0.0)     # (index the cursor is on, when it got there)
        self._rects = []
        self._layout()

    def _layout(self):
        self._rects = []
        y, line = self.y, lh(self.size)
        for it in self.items:
            rows = 1 + (len(wrap(it["desc"], self.width - 6)) if it.get("desc") else 0)
            self._rects.append(pygame.Rect(self.x, y, self.width * cw(self.size), rows * line))
            y += rows * line + int(line * self.gap)
        self.bottom = y

    def item_rect(self, i):
        return self._rects[i]

    def _enabled(self, i):
        return self.items[i].get("enabled", True)

    def _step(self, d):
        for _ in range(len(self.items)):
            self.index = (self.index + d) % len(self.items)
            if self._enabled(self.index):
                return

    def handle_event(self, ev):
        """Returns the index of a chosen item, or None."""
        if ev.type == pygame.KEYDOWN:
            if ev.key in (pygame.K_UP, pygame.K_k):
                self._step(-1)
            elif ev.key in (pygame.K_DOWN, pygame.K_j):
                self._step(1)
            elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                if self._enabled(self.index):
                    return self.index
            elif ev.unicode and ev.unicode.isdigit():
                i = int(ev.unicode) - 1
                if 0 <= i < len(self.items) and self._enabled(i) and "key" not in self.items[i]:
                    self.index = i
                    return i
        elif ev.type == pygame.MOUSEMOTION:
            for i, r in enumerate(self._rects):
                if r.collidepoint(ev.pos) and self._enabled(i):
                    self.index = i
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            for i, r in enumerate(self._rects):
                if r.collidepoint(ev.pos) and self._enabled(i):
                    self.index = i
                    return i
        return None

    def draw(self, surf):
        line = lh(self.size)
        if self._lit[0] != self.index:
            self._lit = (self.index, time.monotonic())
        for i, (it, r) in enumerate(zip(self.items, self._rects)):
            on = i == self.index and self._enabled(i)
            label = "%s[%s] %s" % ("> " if on else "  ", it.get("key", i + 1), it["label"])
            if on and blink(self._lit[1]):
                text(surf, label, r.x, r.y, "bg", self.size, bg="tan")
            elif on:
                text(surf, label, r.x, r.y, "tan", self.size)
            else:
                text(surf, label, r.x, r.y, it.get("c", "fg") if self._enabled(i) else "dim", self.size)
            if it.get("desc"):
                for n, row in enumerate(wrap(it["desc"], self.width - 6)):
                    text(surf, row, r.x + 6 * cw(self.size), r.y + (n + 1) * line, "dim", self.size)
