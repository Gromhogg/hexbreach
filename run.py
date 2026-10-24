"""Run state: the subnet maps, TRACE, credits and held tools."""
import random

import tools
from puzzles import HOPS, NEAR, REGISTRY, WILD, WRONG, at, kinds_for_mode, ramp

SUBNETS = 5
LAYERS = HOPS       # layers of ordinary nodes before the IDS boss
SLOTS = 5           # rows a layer can use
PATHS = 5           # walks used to carve the map; more walks = more branching
SECOND_FOOTHOLD = 1 / 3     # chance a subnet has a foothold besides the one on its last hop

START_CREDITS = 40
FOOTHOLD_TRACE = 25
FOOTHOLD_CREDITS = 15       # less than any puzzle pays: skipping work is never the richest choice
# The going rate for a node, in credits. A kind of puzzle pays its own multiple
# of it, by how hard it is (each puzzle's PAY), so harder ones pay more.
PAY_RATE = 22
PAY_RATE_PER_LEVEL = 2      # and it rises as the nodes get harder
PAY_FAST = 8                # on top, for a solve with the whole timer left; less the more of it was used
PAY_CLEAN = 8               # on top, for a solve without a mistake
CLEAN_MISTAKES = 3          # each mistake takes a third of that; it never goes below nothing
SUBNET_COOLDOWN = 10
# The clock. From the moment a run starts, TRACE rises CLOCK_TRACE % every so
# many seconds, wherever you are: the map, the black market or inside a node.
# It runs faster the deeper into a subnet you are: CLOCK_TICK seconds per rise
# on the first hop, falling evenly to CLOCK_TICK_IDS at the IDS.
CLOCK_TRACE = 1
CLOCK_TICK = 16
CLOCK_TICK_IDS = 10
# TRACE added, by level: the value at the start of each subnet, then at the
# final IDS. Levels rise with every hop (see puzzles/base.py).
MISTAKE_TRACE = [2, 4, 5, 6, 8, 9]
# ...scaled by how bad the mistake was: half for a near miss, double for a wild guess
MISTAKE_SCALE = {NEAR: 0.5, WRONG: 1.0, WILD: 2.0}
TIMEOUT_TRACE = [8, 12, 15, 18, 21, 24]
IDS_TIMEOUT_TRACE = [12, 15, 18, 21, 23, 25]

class Node:
    def __init__(self, layer, slot, kind, name, seed):
        self.id = "%d.%d" % (layer, slot)
        self.layer, self.slot = layer, slot
        self.kind = kind
        self.name = name
        self.seed = seed
        self.next = []          # node ids one layer on
        self.done = False

    def __repr__(self):
        return "Node(%s %s)" % (self.id, self.kind)


class Subnet:
    def __init__(self, level, nodes, boss):
        self.level = level
        self.nodes = nodes      # id -> Node
        self.boss = boss

    def layer(self, n):
        return sorted((x for x in self.nodes.values() if x.layer == n), key=lambda x: x.slot)

    def edges(self):
        return [(a, self.nodes[b]) for a in self.nodes.values() for b in a.next]


def _crosses(edges, layer, a, b):
    return any(l == layer and ((a < c and b > d) or (a > c and b < d)) for l, c, d in edges)


def generate_subnet(rng, level, source):
    """Slay-the-Spire style: a handful of random walks left to right, never
    crossing; the union of the cells they touch is the map. The nodes are
    puzzles, but for a foothold or two. There are no black markets on the way through:
    nobody stumbles on one mid-intrusion. The black market opens once the IDS is down."""
    edges, first = set(), None
    for walk in range(PATHS):
        slot = rng.randrange(SLOTS)
        while walk == 1 and slot == first:
            slot = rng.randrange(SLOTS)
        if walk == 0:
            first = slot
        for layer in range(LAYERS - 1):
            options = [s for s in (slot - 1, slot, slot + 1)
                       if 0 <= s < SLOTS and not _crosses(edges, layer, slot, s)]
            nxt = rng.choice(options)
            edges.add((layer, slot, nxt))
            slot = nxt
    cells = sorted({(l, a) for l, a, _ in edges} | {(l + 1, b) for l, _, b in edges})

    # Footholds: one on the last hop, a breather before the IDS, and sometimes
    # a second on a hop in between, wherever it happens to fall (never the
    # only node of its hop, so the hop keeps a puzzle).
    hops = [[cell for cell in cells if cell[0] == layer] for layer in range(LAYERS)]
    footholds = {rng.choice(hops[-1])}
    spots = [cell for hop in hops[1:-1] for cell in hop if len(hop) > 1]
    if spots and rng.random() < SECOND_FOOTHOLD:
        footholds.add(rng.choice(spots))

    # deal puzzle kinds from a shuffled bag so every type turns up. Only the
    # kinds that have come into play by a layer's level are dealt there.
    bag, known = [], set()

    def deal(layer):
        kinds = kinds_for_mode(source.mode, at(level, layer + 1))
        fresh = [k for k in kinds if k not in known]
        known.update(kinds)
        if not bag:
            bag.extend(rng.sample(kinds, len(kinds)))
        elif fresh:
            bag.extend(fresh)       # a kind that has just come in turns up straight away
        return bag.pop()

    nodes = {}
    for layer, slot in cells:
        kind = "FOOTHOLD" if (layer, slot) in footholds else deal(layer)
        node = Node(layer, slot, kind, source.node_name(rng), rng.getrandbits(32))
        nodes[node.id] = node

    boss = Node(LAYERS, SLOTS // 2, "IDS", source.node_name(rng), rng.getrandbits(32))
    nodes[boss.id] = boss
    for layer, a, b in sorted(edges):
        nodes["%d.%d" % (layer, a)].next.append("%d.%d" % (layer + 1, b))
    for layer, slot in hops[-1]:
        nodes["%d.%d" % (layer, slot)].next.append(boss.id)
    return Subnet(level, nodes, boss)


class RunState:
    def __init__(self, mode, source, seed, unlocked=None):
        self.mode = mode
        self.source = source
        self.seed = seed
        self.rng = random.Random(seed)
        self.unlocked = list(unlocked if unlocked is not None else tools.STARTERS)
        self.level = 1
        self.subnet = generate_subnet(self.rng, 1, source)
        self.position = None
        self.came_from = None       # where the last move started, for backing out of it
        self.trace = 0.0
        self.credits = START_CREDITS
        self.tools = []
        self.tool_slots = tools.START_SLOTS
        self.exploit_used = False
        self.elapsed = 0.0
        self.over = None            # None, "traced" or "won"
        self.abandoned = False
        self.stats = {"nodes": 0, "solved": 0, "failed": 0, "mistakes": 0, "ids": 0, "credits": 0}
        self.solved = {}            # kind -> nodes of that kind solved so far: XOR's own levels go by it
        self.new_fields = []        # manual entries first learned this run
        self.new_unlocks = []
        self.notes = []             # (text, colour) for the map log
        self.markets = {}           # subnet level -> what its market has left to sell
        self.clock = 0.0            # seconds toward the clock's next TRACE tick
        # God mode, for trying things out: credits never run out, TRACE never
        # rises, and any node or subnet can be gone to. Nothing is solved for you.
        self.god = False
        self.god_used = False       # it was on at some point: the run stays out of the records
        self.left_behind = {}       # subnet level -> (subnet, position): subnets a jump has left

    # ---- map
    def available(self):
        if self.over:
            return []
        if self.position is None:
            return self.subnet.layer(0)
        return [self.subnet.nodes[i] for i in self.position.next]

    def path(self):
        """The way in so far: the nodes done in this subnet, in the order they were taken."""
        return sorted((n for n in self.subnet.nodes.values() if n.done), key=lambda n: n.layer)

    def move_to(self, node):
        self.came_from, self.position = self.position, node
        self.stats["nodes"] += 1

    def back_out(self):
        """Undo the last move: step back off a node that was entered but not done."""
        if self.position is not None and not self.position.done:
            self.position = self.came_from
            self.stats["nodes"] -= 1

    def set_god(self, on):
        self.god = on
        self.god_used = self.god_used or on

    def jump(self, level):
        """God mode: go straight to a subnet. Nothing on the way there is marked
        done. The subnet left is kept as it is, for coming back to."""
        if self.over or level == self.level or not 1 <= level <= SUBNETS:
            return False
        self.left_behind[self.level] = (self.subnet, self.position)
        self.level = level
        self.subnet, self.position = self.left_behind.pop(level, None) or (
            generate_subnet(self.rng, level, self.source), None)
        self.came_from = None
        self.exploit_used = False
        return True

    def complete(self, node):
        """Mark a node finished. Clearing the IDS boss moves to the next subnet."""
        node.done = True
        if node.kind == "IDS":
            self.stats["ids"] += 1
            if self.level >= SUBNETS:
                self.over = "won"
                return
            self.level += 1
            self.subnet = generate_subnet(self.rng, self.level, self.source)
            self.position = None
            self.exploit_used = False
            self.trace = max(0.0, self.trace - SUBNET_COOLDOWN)
            self.note("SUBNET %d BREACHED. Trace cools %d%%. Descending..." % (self.level - 1, SUBNET_COOLDOWN),
                      "amber")

    # ---- TRACE
    def add_trace(self, amount):
        if self.god and amount > 0:
            return 0                # god mode: nothing raises TRACE
        self.trace = max(0.0, min(100.0, self.trace + amount))
        if self.trace >= 100.0:
            self.over = "traced"
        return amount

    def clock_tick(self):
        """Seconds per CLOCK_TRACE % of TRACE, by how deep into the subnet you are."""
        hop = min(self.position.layer if self.position is not None else 0, LAYERS)
        return round(CLOCK_TICK + (CLOCK_TICK_IDS - CLOCK_TICK) * hop / LAYERS)

    def tick(self, dt):
        """Time passing anywhere in the run: the clock adds TRACE every clock_tick() seconds."""
        if self.over:
            return
        self.elapsed += dt
        self.clock += dt
        while self.clock >= self.clock_tick() and not self.over:
            self.clock -= self.clock_tick()
            self.add_trace(CLOCK_TRACE)

    def node_level(self, node):
        """Difficulty of a node: the subnet, plus how far through it the node is."""
        return at(self.level, node.layer + 1)

    @staticmethod
    def mistake_cost(level, severity=WRONG):
        return max(1, int(round(ramp(level, MISTAKE_TRACE)) * MISTAKE_SCALE[severity] + 0.5))

    @staticmethod
    def timeout_cost(level, ids=False):
        return round(ramp(level, IDS_TIMEOUT_TRACE if ids else TIMEOUT_TRACE))

    # ---- economy
    @staticmethod
    def score(kind, time_frac, level, mistakes=0, factor=1.0):
        """What a solved node pays, in three parts: (base, speed, accuracy).
        The base follows difficulty: a harder kind of puzzle pays more than an
        easier one, a later node more than an earlier one. On top of it, a
        quick solve and a clean one each earn a bonus. A bonus can shrink to
        nothing but the base is always paid: there are no negative earnings.
        factor is how hard this node came out (Puzzle.difficulty): an easy
        roll pays a smaller base."""
        if kind == "IDS":
            base, parts = 30 + 10 * level, 1
        else:
            base, parts = (PAY_RATE + PAY_RATE_PER_LEVEL * level) * REGISTRY[kind].PAY * factor, 1
        speed = PAY_FAST * parts * max(0.0, min(1.0, time_frac))
        clean = PAY_CLEAN * parts * max(0.0, 1 - mistakes / (CLEAN_MISTAKES * parts))
        return round(base), round(speed), round(clean)

    def reward(self, kind, time_frac, level, mistakes=0, factor=1.0):
        """Credits for a solved node: its score, and what the tools held add to it."""
        return tools.payout(self.tools, sum(self.score(kind, time_frac, level, mistakes, factor)))

    def earn(self, credits):
        self.credits += credits
        self.stats["credits"] += credits

    def can_pay(self, price):
        return self.god or self.credits >= price

    def pay(self, price):
        if not self.god:            # god mode: nothing is taken
            self.credits -= price

    def has(self, tool_id):
        return tool_id in self.tools

    def can_install(self):
        return len(self.tools) < self.tool_slots

    def install(self, tool_id):
        if tool_id in self.tools or not self.can_install():
            return False
        self.tools.append(tool_id)
        return True

    def shop_stock(self, rng, count=3):
        pool = [d for d in self.unlocked if d not in self.tools]
        return rng.sample(pool, min(count, len(pool)))

    def market(self):
        """This subnet's market, open from the map: the same stock however often you
        look, less what you have bought. {"stock": [tool ids], "slot": slots left to buy}."""
        if self.level not in self.markets:
            rng = random.Random(self.seed * 1000 + self.level)
            self.markets[self.level] = {"stock": self.shop_stock(rng, 3), "slot": 1}
        return self.markets[self.level]

    def note(self, text, color="fg"):
        self.notes.append((text, color))
