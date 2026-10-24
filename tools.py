"""Tools: the software you pick up along the way. Each is modelled on a real
kind of program (a protocol dissector, a proxy, a log wiper...), with a game
effect to match. Definitions plus the hooks the run and the puzzle scene call.
Daemons (passive tools) run in the background, always on; active tools have uses
that refill at every node.

"Tools" is what such software is really called. The limit on how many can run
at once (tool slots) is a rule of the game, not something real."""
from collections import namedtuple

Tool = namedtuple("Tool", "id active uses price traceable desc")

# A tool that acts on the target leaves a footprint there, and is traceable:
# every one you carry makes each TRACE gain this much bigger. Tools that only
# run on your own machine (the analysis ones, and your own network set-up) are not.
FOOTPRINT = 0.10

TOOLS = {t.id: t for t in [
    Tool("BRUTEFORCE", True, 1, 60, True,
         "Brute-forces one byte. PAYLOAD: next pick is any byte. XOR: a key byte. IDS: clears one alert."),
    Tool("PROXY", True, 1, 50, False, "Reroutes you through another host: the trace timer stops for 10 seconds."),
    Tool("SNAPSHOT", True, 2, 50, False,
         "Restores a snapshot. PAYLOAD: undo the last pick. Elsewhere: take back your last mistake."),
    Tool("SCANNER", True, 1, 70, True,
         "Scans the node: reveals one piece of the solution. IDS: flags an alert about you."),
    Tool("EXPLOIT", True, 1, 110, True,
         "A ready-made exploit: gets you past a node outright. No credits. Once per subnet, not on an IDS."),
    Tool("STRINGS", False, 0, 40, False,
         "Pulls the readable text out of a dump: keeps the ASCII pane when an IDS blacks it out."),
    Tool("CODEPAGE", False, 0, 60, False,
         "An old PC code page: every byte gets its own symbol in the ASCII pane, never a dot."),
    Tool("DISSECTOR", False, 0, 70, False,
         "A protocol dissector: marks where each header (Ethernet / IP / TCP...) or IDS log entry starts."),
    Tool("MINER", False, 0, 80, True, "Leaves a miner running on every node you solve: +50% credits."),
    Tool("VPN", False, 0, 80, False,
         "An encrypted tunnel that hides your address: -25% to every TRACE gain. Slower: -10% time."),
    Tool("SPOOFER", False, 0, 90, False, "Fakes your address: your first mistake on each node adds no TRACE."),
    Tool("LOGWIPE", False, 0, 80, True, "Wipes your entries from the logs: -3% TRACE after every node you solve."),
    Tool("FILTER", False, 0, 50, False, "Filters your traffic past the IDS's rules: immune to its LOSS and THROTTLE."),
    Tool("HEXDUMP", False, 0, 50, False, "Your own hex dumper: immune to an IDS's DARK and BLIND."),
    Tool("FIREWALL", False, 0, 70, False,
         "Blocks half the trace when time runs out: timeouts add half as much TRACE."),
]}
TRACEABLE_NOTE = "Traceable: +%d%% to every TRACE gain." % round(FOOTPRINT * 100)


def describe(tool_id):
    """A tool's description as shown to the player, with its cost if it has one."""
    tool = TOOLS[tool_id]
    return "%s %s" % (tool.desc, TRACEABLE_NOTE) if tool.traceable else tool.desc


def footprint(held):
    """How much bigger the tools held make every TRACE gain: 0.2 is +20%."""
    return FOOTPRINT * sum(TOOLS[t].traceable for t in held)


# available from the first run
STARTERS = ["BRUTEFORCE", "PROXY", "SNAPSHOT", "MINER", "DISSECTOR", "STRINGS", "VPN", "CODEPAGE"]
# one more unlocks, in this order, each time an IDS is evaded
UNLOCK_ORDER = ["SCANNER", "SPOOFER", "LOGWIPE", "FILTER", "FIREWALL", "HEXDUMP", "EXPLOIT"]

# IDS modifier -> the tool that cancels it
COUNTERS = {"BLACKOUT": "STRINGS", "LOSS": "FILTER", "THROTTLE": "FILTER",
            "DARK": "HEXDUMP", "BLIND": "HEXDUMP"}

# what the tools were called in saves written before they were renamed
RENAMED = {"WILDCARD": "BRUTEFORCE", "FREEZE": "PROXY", "ROLLBACK": "SNAPSHOT", "PING": "SCANNER",
           "BACKDOOR": "EXPLOIT", "ASCII": "STRINGS", "PARSER": "DISSECTOR", "SIPHON": "MINER",
           "OVERCLOCK": "VPN", "GHOST": "SPOOFER", "SCRUB": "LOGWIPE", "STABILIZER": "FILTER",
           "FLOODLIGHT": "HEXDUMP"}

PROXY_SECONDS = 10.0
# A VPN helps and hurts, as a real one does: the target sees the VPN server's
# address, not yours, but the tunnel costs speed.
VPN_TRACE = 0.75
VPN_TIME = 0.90
START_SLOTS = 3
MAX_SLOTS = 5
SLOT_PRICE = 120


def time_limit(held, seconds):
    return seconds * VPN_TIME if "VPN" in held else seconds


def payout(held, credits):
    return int(credits * 1.5) if "MINER" in held else credits


def trace_cost(held, amount, reason, first_mistake=False):
    """TRACE actually added for a mistake or a timeout."""
    if reason == "mistake" and first_mistake and "SPOOFER" in held:
        return 0
    if reason == "timeout" and "FIREWALL" in held:
        amount = amount / 2
    if "VPN" in held:
        amount = amount * VPN_TRACE
    return round(amount * (1 + footprint(held)), 1)


def after_solve(held):
    """TRACE change after a solved node."""
    return -3 if "LOGWIPE" in held else 0


def active_modifiers(held, modifiers):
    """IDS modifiers left after the held tools cancel theirs."""
    return [m for m in modifiers if COUNTERS.get(m) not in held]


def node_charges(held):
    return {d: TOOLS[d].uses for d in held if TOOLS[d].active}
