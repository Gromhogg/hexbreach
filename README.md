# HEXBREACH

A hex-dump netrunning roguelike. Every node on the network is a puzzle played
on a Wireshark-style hex dump (`offset | 16 hex bytes | ASCII`). Break five
subnets without letting TRACE reach 100%.

It is also, optionally, secretly useful: in PROTOCOL and LIVE mode the bytes
are real packets, so the skills the puzzles reward are the skills you need to
read a hex pane.

```
./run.sh
```

`run.sh` activates the virtualenv in `.venv` (creating it and installing
`pygame-ce` if it is missing) and starts `main.py`. On a Mac it first puts up
a small popup with a progress bar (see Starting up). The only dependency is
pygame-ce; Python 3.10 or newer.

On a Mac there is no need for a terminal: double-click `HEXBREACH.app` in this
folder, or drag it to the Dock. It runs `run.sh`.

## Tutorial

**TUTORIAL** on the title screen (it is the item under the cursor until you
have finished it once) takes about two minutes. Five steps on one real HTTP
frame, nothing to lose:

1. **Offsets**: click the byte at a given offset (row + column).
2. **Hex and ASCII**: find text in the ASCII pane and click it.
3. **Fields**: drag across the four bytes of the IPv4 Source Address.
4. **Values**: read a byte and type it in hex.
5. **The run**: timer, TRACE, and how difficulty rises.

A wrong answer costs nothing and tells you what you clicked; the second one
lights up the answer. A panel on the right shows the byte under the cursor as
offset, hex, decimal, binary and ASCII. ESC leaves at any point.

## Data modes

You pick one at the start of each run.

| Mode     | Bytes come from                                              | Useful for                            |
|----------|--------------------------------------------------------------|---------------------------------------|
| RAW      | random bytes                                                 | nothing, just a game                  |
| PROTOCOL | synthesized valid packets (Ethernet/IPv4/TCP/UDP/DNS/HTTP)   | learning to read real hex / Wireshark |
| LIVE     | your own `.pcap` / `.pcapng` files in `captures/`            | reviewing your own network traffic    |

## A run

- 5 subnets. Each is a branching map of 6 hops ending in an IDS (an intrusion
  detection system: the boss). Click a highlighted node (or press its number)
  to move. The map lights the path you have taken, node to node. A full run
  is 35 nodes, roughly 30-45 minutes.
- **TRACE** is your health: 0-100%. The bar is on every screen of a run, with
  the clock's rate next to it: from the moment a run starts, TRACE rises 1%
  every 16 seconds, wherever you are (the map, the black market, inside a
  node). The clock runs faster the deeper you are in a subnet: a second less
  per hop, down to 1% every 10 seconds at the IDS. Every puzzle has a
  countdown. A mistake adds a little TRACE (2% at the first node, 9% at the
  last), a timeout adds a lot (8% rising to 24%), 100% ends the run. Clearing
  a subnet cools it by 10%.
- **How much a mistake costs depends on how bad it was.** A near miss costs
  half, a wild guess double (1% / 2% / 4% at the first node, 5% / 9% / 18% at
  the last). The log says which it was.

  | Puzzle   | Near miss (half)                                   | Wild guess (double)                               |
  |----------|----------------------------------------------------|---------------------------------------------------|
  | HUNT     | one cell off an occurrence, or on bytes matching at least half the pattern | a byte value the pattern does not contain |
  | CARVE    | inside a file, past its signature                  | a byte no known signature starts with             |
  | PAYLOAD  | the flushed buffer was one byte short of a sequence | it did not hold even half of any sequence        |
  | XOR      | a bit or two out, or at least half the key bytes right; a click a byte or two off the pattern | no byte right and half the bits wrong |
  | DISSECT  | the selection overlaps the field                   | it is not even in the field's header              |
  | REASSEMBLE | a segment dropped a byte or two off, or a row off, from where it goes | a segment dropped where it runs past the end of the stream |
  | CHECKSUM | the right byte, moved closer to the value that fixes it | a byte the checksum does not cover           |
  | IDS      | a click on a fake (a copy of the pattern in DEST, or a SOURCE one byte off it) or an edit of its ALERT byte, a wrong CHECK value, ENTER with one thing left | a byte that is not an ALERT (or CHECK) byte |

  Anything in between is an ordinary mistake: falling for a CARVE decoy,
  naming the wrong file type, selecting a different field of the same header.
- Solving nodes pays credits, and pay follows difficulty: a harder kind of
  puzzle pays more than an easier one (from least to most: HUNT, CARVE,
  DISSECT, PAYLOAD, XOR, REASSEMBLE, CHECKSUM) and a later node pays more than an earlier
  one. That is the base, and it is always paid. On top of it come two bonuses:
  up to 8 credits for speed (all of it with the whole timer left) and up to 8
  for accuracy (all of it with no mistakes; each mistake takes a third, and a
  mistake taken back with SNAPSHOT does not count). A bonus can shrink to
  nothing but pay never goes below the base. An IDS pays a bigger base of its
  own (30 + 10 per level). The result line says how the
  pay was made up: `pay: 22 base, +8 speed, +5 accuracy`. A **FOOTHOLD** is a host nobody is
  watching: clear your logs there (TRACE -25%) or run a miner for a few
  credits (15, less than any puzzle pays).
- **The black market opens when an IDS goes down.** There are no black markets among the
  nodes: nobody stumbles on one in the middle of an intrusion. Clear a
  subnet's IDS and, before the next subnet, you can spend what you earned on
  tools and tool slots.
- **No two subnets look alike.** A map is carved by a handful of random walks
  from left to right that never cross, so routes split and merge as they
  fall. The nodes are puzzles, but for a foothold or two: one is always on
  the last hop before the IDS, and now and then there is a second somewhere
  in between. A route may pass a foothold or miss them all, so the whole map
  is worth reading before you pick an entry node.
- Running out of time never gets you through a node. Once time is up, TRACE
  rises every 0.5 seconds: over 4 seconds that adds up to the timeout cost
  (for an IDS, 15% on the first, rising to 25% on the last). Finish the puzzle
  anyway and its base pay is halved. Or press ESC to jack out: the node is not
  cleared, and you do it again with a fresh puzzle and a fresh briefing.
- The moment TRACE reaches 100% the end-of-run report comes up, typed out.
  It stays for 15 seconds (SPACE cuts that short), then the line drops: the
  screen goes dark and the title screen boots again.

## Puzzles

| Puzzle   | What you do                                                                     | Modes          | First appears     |
|----------|---------------------------------------------------------------------------------|----------------|-------------------|
| HUNT     | Click every occurrence of a byte pattern in the dump                            | all            | subnet 1, hop 1   |
| CARVE    | File carving: find the files embedded in the stream by their signatures (magic numbers), and say what each is, from nine choices | all | subnet 1, hop 1 |
| DISSECT  | Drag across the bytes of a named field ("TCP > Destination Port")               | PROTOCOL, LIVE | subnet 1, hop 1   |
| PAYLOAD  | A breach: pick bytes off a square grid, alternating row / column, to spell three chained sequences before the buffer fills. Ranked by the deepest one you get in | all  | subnet 1, hop 3   |
| XOR      | The dump is XORed with a short repeating key; recover it from a few bytes of known plaintext. Four levels of its own | all | subnet 2, hop 1 |
| REASSEMBLE | A stream arrived in segments, out of order. Drag each segment to where its data goes: offset = its seq - the stream's first seq | all | subnet 3, hop 1 |
| CHECKSUM | One header byte is corrupted; change a byte so the IPv4/TCP/UDP checksum validates | PROTOCOL, LIVE | subnet 2, hop 4 |
| IDS      | The boss: one of several games, named by the briefing's tag. ALERT LOG: the IDS's log of alerts as fixed-size entries; find every copy of your address in SOURCE, as in HUNT, clear that entry's ALERT byte, then commit the log; with view modifiers | all | end of each subnet |

Each puzzle opens with a briefing; the timer only starts when you jack in.
The briefing is one box and a glance, not a read: what to do in a line, the
same job as numbered steps, a few facts about this node (the pattern, how
many files, the key length...), then the numbers: the time limit and what it
pays. Beside the box, where the side panel will be, the job plays in
miniature: a few seconds of animation on a loop (the mouse finds the bytes,
clicks, the answer goes in) that shows how and never where. For an IDS the
box also lists what it does to the hex view (its view modifiers), under the
rows about the log. While a node runs, the timer is a plain number of whole
seconds.

Every node also lists its job as steps: one to five short tasks, in order,
under TASKS at the top of the side panel. The one you are on is marked `[>]`
and repeated in amber above the dump; done ones are ticked `[x]`; some carry
a count (`Find E1 26 ED 70 (1/3)`). A task says what to find or type, not
how to click: the tutorial covers that. The briefing shows the same
steps, numbered, under DO. Follow them or ignore them: nothing is hidden
behind them, and an expert loses nothing.

**PAYLOAD is a breach, and it is ranked.** The grid is square (5 by 5 at
first, 8 by 8 in the last subnet). Your first pick is from the top row, the
next from that byte's column, then from that byte's row, and so on, each byte
going into the buffer. There are three sequences to spell, shortest first,
and they chain: the last byte of one is the first byte of the next, so it is
picked once and counts for both. The panel's NEXT BYTE line says what the
sequence you are on needs next, counting what the buffer already ends with. The
buffer has room for little more than the whole chain (2 spare picks in
subnet 1, then 1, then none). The breach ends when all three are in, when the
buffer fills, or when you press ENTER (or click the upload line in the
panel), and it is ranked by the deepest sequence in the buffer: a SHALLOW
BREACH pays half the going rate, a BREACH the full rate, a DEEP BREACH
double. Any rank clears the node; the briefing says what each pays here. A
full buffer with no sequence in it is the mistake: flushed, and you start
again from the top row.

**REASSEMBLE is how TCP puts a connection back together.** A stream was
cut into segments and they arrived out of order. The dump has two parts. At
the top is the stream, starting at offset `0000`, its bytes shown `__` until
they are filled. Under it, one segment a row: first its sequence number (seq,
tinted), then its data. The task gives the stream's first seq.

1. Pick a segment and read its seq.
2. Work out where it goes: offset = seq - the first seq, in hex.
3. Drag the segment there, and let go on the byte where its data starts.

```
first seq 3C00
segment   3C 1A 4F 4B 21      seq 3C1A: 3C1A - 3C00 = 1A
                              drag it to offset 001A
```

While a segment is dragged over the stream, its bytes show where they would
land. Let go anywhere else and nothing happens. It gets harder as it goes:
the seq starts as 1 byte with the stream at seq `00` (seq is the offset),
then the stream starts somewhere else, then the seq is 2 bytes, then 4 bytes
as in real TCP. Later there are segments that are not part of the stream (a
seq before its start or past its end: leave them), segments sent twice
(resends), and a resend that covers the end of one segment and the start of
the next. In the last subnet a 4-byte seq can run past `FFFFFFFF` and on from
`00000000`, as real ones do.

**XOR has four levels of its own, and a run climbs them one solved XOR at a
time.** The first XOR you solve in a run is level 1, the second is level 2,
the third is level 3, and every one after that is level 3 or 4, wherever on
the map it is. The briefing says which (`XOR LEVEL 3 of 4`).

| XOR level | Key          | Known plaintext              | What you do                                 |
|-----------|--------------|------------------------------|---------------------------------------------|
| 1         | 1 byte       | zero padding, 4 to 8 bytes   | find where the key repeats, and read it off |
| 2         | 2 or 3 bytes | zero padding, 6 to 12 bytes  | the same, with a longer pattern             |
| 3         | 1 byte       | text                         | work one key byte out, bit by bit           |
| 4         | 2 bytes      | text                         | work two key bytes out                      |

In PROTOCOL and LIVE the known bytes are the packet's own (`08 00 45 00` at
0x000C), so there a level is a key length, 1 to 4 bytes. A key byte that
lines up with a `00` is read off; the others are worked out.

**A double XOR has a second key under the first.** Once a run has solved
three XORs, about one XOR node in five is encrypted twice: a block of the
dump with one key, then the whole dump with another. The briefing says so:
`Work out two keys, one after the other.` and `XOR LEVEL 2 of 4, then 3 of
4`.

1. Work out the first key as usual, and press Enter.
2. The dump changes: all of it decrypts but the block. The second key's
   known bytes are in the block: marked if they are text, a new pattern to
   find if they are zero padding.
3. Work out the second key the same way, and press Enter.

Each key has an XOR level of its own, any of the four, and is 1 or 2 bytes.
Both are level 4 only in the final subnet. A double XOR has half as much time again, and pays half
as much again. A wrong second key costs TRACE as usual, but the first key
stays in. A tool that reveals a key byte reveals one of the key you are on.
With two patterns in the dump, a click on the other key's pattern costs
nothing: the log says it is not the one.

In PROTOCOL and LIVE the block is the IPv4 packet inside the frame. The first
key's known bytes are the EtherType (`08 00` at 0x000C), the second key's the
start of the IPv4 header (`45 00` at 0x000E), so each key is 1 or 2 bytes.

**Over zero padding, find the pattern first.** A few bytes of the plaintext
are zero. Anything XOR 00 is itself, so there the key shows through: a few
bytes in a row that are the key, repeating. The padding is as long as the
key, a few times over, so the pattern is not always the same length:

```
2D 2D 2D 2D 2D                 a 1-byte key: 4 to 8 bytes
2D C9 2D C9 2D C9              a 2-byte key: 6, 8 or 10 bytes
2D C9 71 2D C9 71 2D C9 71     a 3-byte key: 9 or 12 bytes
```

The first step says how long it is (`Find 9 bytes where the key repeats`),
and it is always in one row of the dump. Nothing marks the bytes, and the
briefing does not say where they are. Find them in the dump and click any one
of them. Then they are marked, and the steps
name the bytes. A click anywhere else is a mistake, and the key cannot be
typed until the pattern is found. Known text, and a packet's known bytes, are
not a pattern you can see: those are marked from the start.

**A key byte that is read off is typed in hex.** Over a `00` the key shows
through: the task says `Type k0 = 2D XOR 00`, and you type `2D`.

**A key byte that has to be worked out is typed as bits.** The task says so:
`Type the bits of k0 = 82 XOR 41`. The panel writes both bytes as bits, one
over the other:

```
  82 = 1000 0010
  41 = 0100 0001
  k0 = ____ ____
```

Go along the columns from the left. Where the two bits are the same, type
`0`. Where they differ, type `1`. Here that is `1100 0011`. The `k0` row
fills in as you type, and the `KEY >` line shows the byte in hex (`C3`): the
game turns the bits into hex for you. Each four bits make one hex digit: they
are worth 8, 4, 2 and 1, and 10 to 15 are written A to F.

The dump decrypts as you type: when a key byte is right, the highlighted
bytes it lines up with read as the known plaintext. Backspace takes back the
last bit or digit.

**The side panel holds only what a puzzle cannot be solved without.** For
XOR that is the key so far, and the bits above. For the IDS it is a key
that says where the SOURCE, ALERT and CHECK fields are.

**The IDS holds a game of its own.** The node at the end of a subnet is
always marked IDS on the map, but what is behind it is one of several games,
and the briefing's tag says which. There is one so far.

**ALERT LOG.** The dump is the IDS's log of alerts: entries of 12 or 16 bytes,
back to back, each with the same fields (time, source address, destination
address, port, priority, an ALERT byte that is `01` while the alert is live
and `00` once cleared). The pattern to find is your own address: the first
task gives it. The first step is a HUNT: click every
copy of the pattern in a SOURCE field, and it is marked as found. Any other
address you click is a mistake. Then find that entry's ALERT byte, click it, type
`00`, and when none is left press ENTER to commit the log. A copy of the
pattern in the DEST field is traffic *to* you and does not count; nor does a
SOURCE that is a byte off the pattern. From the fourth IDS every entry has a CHECK byte, the XOR of
its other bytes: clearing an alert breaks it, so it has to be put right too,
or the log is rejected. This is how fixed-size records (logs, tables, file
headers) are read in a hex dump: work out the record size, count to the
field, read it.

Nothing in the dump marks the ALERT byte. The KEY in the side panel says where
it is. At the first two IDS one row of the dump is one entry, so the key names
columns, the numbers along the top of the dump:

```
KEY
  SOURCE  columns 04-07
  ALERT   column 0F
```

Find the pattern, stay on its row, and go across to column `0F`. From the
third IDS the rows no longer line up with the entries, so there is no one
column. The key counts from the pattern instead:

```
KEY
  ENTRY   12 bytes long
  SOURCE  starts 7 bytes into an entry
  ALERT   1st byte after the pattern
  CHECK   5th byte before the pattern
```

`1st byte after` is the byte right next to the pattern's last byte. The count
runs on into the next row when it reaches the end of one.

Three notes on realism. REASSEMBLE's segments carry only a seq: a real TCP
segment has the rest of its header around it, and the receiver also checks
which connection it belongs to. PAYLOAD's goal (getting exact byte sequences into a
buffer) is real, but its row/column rule is the game's own. CARVE only uses signatures that do not print their own name: a file
that shows `%PDF-` or `GIF89a` in the ASCII pane is no test, so those formats
are left out of the puzzle and listed in the logs instead. The
signature table stays on screen, bytes and all, at every level.

IDS modifiers: THROTTLE (rate-limited: rows arrive slowly), BLACKOUT (no ASCII pane), BLIND (no
offsets), LOSS (a few bytes never arrive, shown ??), DARK (you only see bytes near
the cursor). The first IDS draws one of the first three; LOSS joins from
the second IDS and DARK from the third. Later IDS stack two, then three.

## Difficulty

It starts easy and rises with every hop, not once per subnet. A node's level
is its subnet plus how far through the subnet it is: the first node of a run
is level 1.0, each hop adds 1/6, and the last IDS is 6.0.

- **New puzzle kinds arrive one at a time** (table above), each at its
  simplest.
- **The IDS grows harder each subnet**: 2 entries to clear at the first, 5
  at the last, in a log of 8 entries growing to 16. From the second IDS there
  are decoys: your address as DEST, and one SOURCE a byte off yours. From the
  third the fields come in a different order each time and the rows no
  longer line up with the entries. From the fourth each entry carries a
  CHECK byte to fix as well.
- **Timers shrink a little every hop**: HUNT goes from 90 s to about 48 s,
  DISSECT from 80 s to about 46 s, across the run.
- **Dumps grow**: 96 bytes at the first node (64 for CARVE), 448 by the end
  (anything over 384 has to be scrolled).
- **CARVE marks nothing.** No byte in the dump is tinted: the signatures
  have to be read out of the bytes, against the table on the panel. The table
  shows how each one reads in the ASCII pane when it reads as letters (ZIP is
  `PK..`, EXE is `MZ..`), which is how they are spotted in practice.
- **Each puzzle steps up at its own points**, so something changes at most
  hops. HUNT: 2 occurrences of a 4-byte pattern, up to 5 of a 2-byte one.
  CARVE: 1 file and no decoys, up to 3 files and 4 decoys, from a longer list
  of signatures. PAYLOAD: sequences of 2, 3 and 4 bytes on a 5 by 5 grid, up
  to 3, 5 and 6 on 8 by 8 with no spare buffer. XOR: its own four levels, one solved XOR at a time, and after three a double XOR now and then (see Puzzles). DISSECT: 2 fields up to 5. REASSEMBLE: 3 segments up to 6, a longer seq, then segments that are not part of the stream, resends, and a seq that wraps. CHECKSUM: the
  bytes it covers stop being tinted, then TCP/UDP checksums join, then the
  panel stops working out the error for you.
- **DISSECT's help fades per protocol.** In the first subnet a protocol
  appears in, the panel gives each field's offset and size ("IPv4 header
  starts at 0x000E, field is at +0x08, 1 byte"); in the next subnet only its
  size; after that nothing. Ethernet/IPv4/IPv6 start in subnet 1, TCP/UDP in
  2, DNS in 3, HTTP in 4.
- **TRACE costs rise** as listed under "A run". An IDS gets about one normal
  node's time, falling with level (55 s at the first, 36 s at the last).
- New packet types still arrive by subnet: TCP options from 2, DNS from 3,
  HTTP from 4, IPv4 options in 5.

## Controls

| Input                      | Does                                              |
|----------------------------|---------------------------------------------------|
| mouse over a byte          | a blinking block cursor marks it in both the hex and ASCII panes |
| click                      | pick a byte (PAYLOAD, HUNT, CHECKSUM, CARVE, IDS; XOR: the pattern) |
| drag                       | select a range (DISSECT); move a segment (REASSEMBLE) |
| wheel, arrows, PgUp/PgDn   | scroll long dumps                                 |
| `0-9` `a-f`, Backspace, Enter | hex entry (XOR key, CHECKSUM byte, IDS log byte); `0` and `1` are the bits of an XOR key byte that has to be worked out |
| `1`-`9`                    | answer a CARVE "what is it?" (or click the line)  |
| Enter                      | PAYLOAD: end the breach and upload what is in the buffer. IDS: commit the log (or click the line) |
| `Q` `W` `R` `T` `Y` (or F1-F5) | use the tool in slot 1-5 (or click it) |
| Space / Enter              | jack in, continue                                 |
| `M`                        | the menu: every key, a searchable list of terms that says which are real, the logs, and the fullscreen switch. Anywhere except while a node's timer is running |
| `L`                        | the logs: every field and file signature you have dissected. Same places as `M` |
| drag across text           | highlight it, as in a terminal; `cmd+C` copies it. A plain click still clicks |
| Esc                        | go back one level: mode select, toolkit, a node's briefing, a FOOTHOLD node, the logs, the menu, the tutorial |
| click a level of the path line | go back to that level                         |
| Esc twice on the map       | abandon the run (so does clicking the path above the map, twice) |
| arrows + Space on the map  | pick a highlighted node, then move to it          |
| rest the mouse on a map node | see its briefing                                |
| wheel, PgUp/PgDn on the map | look back through the session log                |
| cmd+F, F11 or alt+Enter    | fullscreen on / off, anywhere (also an item in the `M` menu) |
| click `[GOD MODE]`, bottom right | god mode on / off, on any screen of a run (see "God mode") |

## God mode

A button in the bottom right corner of every screen of a run, for trying things
out. Click it to switch god mode on or off; it is lit while it is on, and it
stays as set for the next run until the game is closed. While it is on:

- **Credits never run out.** The header shows `CREDITS ∞`, everything in the
  black market can be bought, and nothing is taken for it.
- **TRACE never rises**, so you are never traced: not by the clock, a mistake
  or overtime. It can still fall. Switched off, it rises again from where it
  was.
- **Any node can be gone to.** Click any node on the map, the IDS included,
  not only the next ones. Nothing is solved for you: the node you go to still
  has its puzzle, and the nodes you skipped stay undone.
- **Any subnet can be gone to.** The map shows `SUBNET 1 2 3 4 5` in the
  top right; click a number to go straight to that subnet. No IDS is counted as
  evaded on the way. A subnet you leave this way is kept as it was, for coming
  back to.

A run that had god mode on at any point is left out of the records (runs,
wins, deepest subnet, best time), and the end-of-run report says so. Tools
unlocked by evading an IDS and fastest solves are still kept: those puzzles
were solved for real.

## Display

The game is laid out on a grid of at least 1280x800 units and drawn at the
display's real pixel density, so text is sharp on a Retina screen: a window
there is rendered at 2560x1600. The window can be resized, and fullscreen
fills the display. Either way the layout is scaled to fit and then grows to
reach all four corners, the way a terminal has more columns in a wider window:
there are no black bars at any shape, and the text is re-rendered at that size
rather than stretched. Letters are drawn a little heavier than the font's bare
outlines, the way macOS draws text, so they look as they do in a terminal
(`WEIGHT` in `ui.py`). Fullscreen or not is remembered in `save.json`;
`--fullscreen` and `--windowed` override it for one launch.

Whatever is under the cursor blinks like a terminal cursor: the byte under the
mouse, the selected menu item, the map node you are pointing at. A selection
you are dragging stays solid.

The top line of every screen is the path you are on, as `pwd` would print it.
It starts at the game's real directory and grows as you go deeper:
`.../hexbreach/protocol/subnet2/10.0.0.1:22/ids`.

The path is also how you go back. Point at a level and it lights up if there
is something to go back to; click it to go there. Esc goes back one level.

- From the toolkit screen: `protocol` returns to the choice of mode, `hexbreach` to
  the title. Nothing is recorded; the run had not begun.
- From a node's briefing, or a FOOTHOLD node: `subnetN` returns to the map as if
  you had never entered, and you may pick a different node.
- Once you jack in there is no way back: the timer is running, and Esc and
  the path do nothing until the node is solved or times out.
- From the map, going back up means giving up the run, so it has to be asked
  for twice.
- The black market, which opens after an IDS, is simply left, as its LEAVE item does:
  `subnetN` goes on to the next subnet's map.
- In the tutorial, `tutorial` restarts it and `hexbreach` leaves.

Every screen types itself out, fast, when it first appears: the title on
launch and after a run, and each new window after that (mode select, the
toolkit, the map, a briefing, the black market, the menu...). Coming back to a screen
that was already up does not retype it, and any key shows the rest at once.

The title screen has the name in large type in the top left. Under it, what
the game is is spelled out in the ASCII pane of a hex dump, and that dump is
live like any other: point at a letter or at its byte and the cursor marks
both, drag to move the selection. It is read-only.

Nothing shakes when TRACE rises: a mistake flashes a red border and that is
all. Nothing on screen shakes or flickers.

Meters are drawn the way a terminal draws them, `TRACE [||||||||      ] 62%`,
not as solid blocks.

## Tools

The software you pick up along the way. "Tools" is what such programs are
really called, and each one here is modelled on a real kind of software. What
is not real: the limit on how many you can run at once (**tool slots**: 3 to
start, 5 at most), credits, and the black market. Those are rules of the game, and the
tutorial says so.

Active tools have uses that refill at every node; daemons (passive tools) are always on. B on the map opens the black market.

**Traceable tools.** A tool that acts on the target leaves a footprint there,
and that is what gets intruders caught. Each traceable tool you carry (MINER,
SCANNER, BRUTEFORCE, EXPLOIT, LOGWIPE) makes every TRACE gain 10% bigger; the
tools list shows the total as `footprint +20%`. Tools that only run on your
own machine, the analysis ones and your own network set-up, cost nothing. More
tool slots therefore means more room to make yourself easier to trace.

| Tool       | Kind    | The real thing                              | Effect in the game                                   |
|------------|---------|---------------------------------------------|------------------------------------------------------|
| BRUTEFORCE | active  | trying every possible value                 | PAYLOAD: next pick matches any byte. XOR: reveals a key byte, and the pattern with it. REASSEMBLE: puts one segment in. IDS: clears one alert |
| PROXY      | active  | rerouting your traffic through another host | stops the trace timer for 10 s                       |
| SNAPSHOT   | active  | restoring a saved state                     | PAYLOAD: undo the last pick. Elsewhere: take back your last mistake |
| SCANNER    | active  | a port / host scanner                       | reveals one piece of the solution. XOR: the pattern, while it is still to find. REASSEMBLE: where one segment goes. IDS: flags an alert about you |
| EXPLOIT    | active  | ready-made code for a known vulnerability   | gets you past a node outright, once per subnet, not on an IDS |
| STRINGS    | daemon  | the `strings` utility: readable text in a binary | keeps the ASCII pane when an IDS blacks it out  |
| CODEPAGE   | daemon  | code page 437, the character set of the first IBM PCs | every byte gets its own symbol in the ASCII pane, never a dot, so HUNT fakes no longer look like copies there |
| DISSECTOR  | daemon  | a protocol dissector, as in Wireshark       | marks where each header starts in a packet dump, or each entry in an IDS log |
| MINER      | daemon  | a cryptominer left running on a machine     | +50% credits                                         |
| VPN        | daemon  | an encrypted tunnel that hides your address | -25% to every TRACE gain, but -10% time              |
| SPOOFER    | daemon  | forging your source address                 | first mistake on each node is free                   |
| LOGWIPE    | daemon  | a log cleaner                               | -3% TRACE after every solved node                    |
| FILTER     | daemon  | a packet filter                             | immune to LOSS and THROTTLE                          |
| HEXDUMP    | daemon  | a hex dumper such as `xxd`                  | immune to DARK and BLIND                             |
| FIREWALL   | daemon  | a firewall                                  | timeouts cost half                                   |

BRUTEFORCE, PROXY, SNAPSHOT, MINER, DISSECTOR, STRINGS, VPN and CODEPAGE are available from the start. Each IDS you get past, in any
run, unlocks the next one for future runs.

## What carries between runs

`save.json` in this folder: unlocked tools, deepest subnet reached, best
full-clear time per mode, fastest solve per puzzle type, whether you have
finished the tutorial, and the **logs**. The logs fill in as you first solve each protocol field in
DISSECT / CHECKSUM and each file signature in CARVE, with its offset, size, an
example value from your own game and a one-line explanation. It doubles as a
real reference. Delete `save.json` to start over.

## LIVE mode: playing your own traffic

Drop `.pcap` or `.pcapng` files into `captures/` and choose LIVE.

To record one in Wireshark:

1. Install Wireshark from <https://www.wireshark.org> and open it.
2. Double-click your network interface in the list (on a Mac, Wi-Fi is usually
   `en0`). Capturing starts immediately.
3. Use the network for a minute: load a few sites, and for readable packets
   visit a plain-HTTP page such as `http://neverssl.com`.
4. Press the red square to stop, then **File > Save As...** and save into this
   project's `captures/` folder. Either format works (pcapng is the default).

Or from a terminal:

```
sudo tcpdump -i en0 -c 2000 -w captures/home.pcap
```

What to expect:

- Map nodes are named after real IP:port endpoints from your capture.
- Most modern traffic is encrypted (TLS, QUIC). Encrypted payloads are treated
  as noise; the header puzzles (DISSECT, CHECKSUM, XOR's known bytes) still
  work, because headers are never encrypted.
- IPv6 packets show up in DISSECT with their own page in the logs.
- Captures usually hold blank checksums for packets your machine sent (the
  network card fills them in later). CHECKSUM repairs them before corrupting a
  byte, so the puzzle is always solvable.
- If `captures/` is empty, or holds fewer than 12 packets with a readable IP
  header, LIVE falls back to synthesized PROTOCOL packets and says so on the
  mode screen. A puzzle that needs something the capture lacks (say TCP, in a
  UDP-only capture) borrows a synthesized packet the same way.
- **Everything stays local.** Capture files are only read from disk and parsed
  in memory. The game has no network code and writes nothing but `save.json`,
  which holds field names and example values you solved (addresses and ports
  from your capture can appear there as examples). `captures/` is in
  `.gitignore`.
- Supported: classic pcap (either byte order, micro/nanosecond), pcapng;
  Ethernet, raw IP, loopback and Linux cooked link types. At most 64 MB per
  file and 20,000 packets in total are read.

## Starting up

On a Mac, `run.sh` puts a small popup on screen at once: a hex dump whose
bytes arrive as the game loads, the step the start has reached, and a bar,
`[||||||||      ] 45%`. It is a separate small program (`splash/`), so it is
up and moving before Python and pygame have loaded, and the game never waits
for it. It takes no clicks and no keys.

- It closes once the title screen is drawn. In fullscreen it fills its bar
  and closes as the window begins its slide to fullscreen: macOS takes it off
  screen for the slide.
- It stays up for about a second at the least, so a fast start still plays.
- If the game fails to start, it says `start failed` in red for three seconds
  rather than fill its bar.
- With no popup (it has not been built, or it stops) the game starts as it
  always did. `HEXBREACH_NO_SPLASH=1 ./run.sh` starts without it.

`splash/hexbreach-splash demo` plays the popup by itself. After editing
`splash/splash.swift`, run `splash/build.sh` (it needs Apple's developer
tools). `HEXBREACH_SPLASH_LOG=file` logs when each step happened, and
`HEXBREACH_SLOW_START=1` makes the game wait a second at each step, to watch
the popup work.

## Tests

```
.venv/bin/python -m unittest discover -s tests
```

- `tests/test_packets.py`: build -> parse round trips, checksum validation, a
  54-byte Wireshark-style TCP/443 frame, truncated and garbage input.
- `tests/test_puzzles.py`: 1,000 seeds per puzzle type and mode. The
  generator's own solution must pass its validator and solve the puzzle through
  the normal inputs with no mistakes, so every puzzle is solvable. The seeds
  cover every hop of every subnet. Also map generation, the rules of each
  puzzle, and the difficulty gradient: no setting ever gets easier from one
  hop to the next, the first node is gentle, kinds come in one at a time.
  Also the task list: one step current at a time, all ticked once solved,
  and the line above the dump is the current step.
- `tests/test_pcap.py`: the pcap / pcapng readers on generated files.
- `tests/test_smoke.py`: the whole game loop headless (`SDL_VIDEODRIVER=dummy`),
  driven by scripted mouse and keyboard events through the tutorial and
  complete runs in every mode. Also the display: scaling to Retina and
  fullscreen sizes, the fullscreen switch, and the blinking cursor.
- `tests/test_god.py`: god mode headless: the button, credits, TRACE, going
  to any node or subnet, and the records.
- `tests/test_startup.py`: the starting-up popup: the lines the game sends
  it, a popup that is missing, gone or stuck, `run.sh`, and that the popup's
  colours and title are the game's.
- `tests/visual_check.py` (not a unit test): plays the tutorial and one node
  of every puzzle type in every mode in the real window and writes screenshots
  to `tests/shots/`.

Developer shortcuts:

```
./run.sh --puzzle XOR --mode PROTOCOL --level 3    # practice one puzzle, as hard as subnet 3's first hop
./run.sh --puzzle HUNT --level 5.5                 # levels take fractions: halfway through subnet 5
./run.sh --seed 42                                 # reproducible run
./run.sh --autoplay --mode LIVE                    # watch the test bot play
./run.sh --fullscreen                              # or --windowed; otherwise as you last left it
```

## Layout

```
main.py        entry point, game loop, scene stack
scenes.py      title, tutorial, mode select, toolkit, map, puzzle, black market, foothold, menu, logs, game over
glossary.py    the terms and definitions behind the menu's TERMS page
hexview.py     the hex-dump widget: linked cursor, click / drag select, highlights, IDS effects
ui.py          the view (layout units -> pixels), text drawing, log panel, bars, menus
packets.py     build + parse Ethernet/IPv4/IPv6/TCP/UDP/DNS/HTTP, checksums, field map
sources.py     ByteSource: RandomSource, SynthSource, PcapSource (own pcap + pcapng reader)
puzzles/       base.py + one file per puzzle type + ids.py (the IDS slot: view effects, which game) + alertlog.py
run.py         run state: map generation, TRACE, credits, tools held
tools.py       tool definitions and hooks
save.py        JSON save
autoplay.py    the bot used by the smoke test and --autoplay
startup.py     the game's line to the starting-up popup: one line per step of the start
splash/        the starting-up popup: splash.swift, build.sh, and the built hexbreach-splash
captures/      drop .pcap / .pcapng files here for LIVE mode
tests/
```

The key idea: puzzles never know where bytes came from. They ask a
`ByteSource` for a buffer or a parsed packet, so the three modes are just
three sources.

Difficulty numbers live in plain tables at the top of each puzzle class
(`SIZE`, `TIME`, ...), in `puzzles/alertlog.py` and `puzzles/ids.py`, in `run.py` (TRACE costs,
rewards, map shape) and in `tools.py` (prices). There are two kinds of
table, both read against a node's level (`puzzles/base.py`):

- a **ramp** is a list of six numbers: the value at the start of subnets 1-5,
  then at the final IDS. Hops in between are interpolated.
  `TIME = [90, 75, 65, 58, 52, 48]`
- a **step** table is `(from level, value)` pairs, written with
  `at(subnet, hop)`. `KEYLEN = [(at(1), 1), (at(2, 5), 2), ...]` reads "1 byte
  from the start, 2 bytes from subnet 2 hop 5".

`first = at(subnet, hop)` on a puzzle class is when that kind starts turning
up on the map.
