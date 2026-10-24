"""Meta-progression: one JSON file in the project folder."""
import json
import os

import tools

VERSION = 1


def default_path():
    return os.environ.get("HEXBREACH_SAVE") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "save.json")


def _blank():
    return {
        "version": VERSION,
        "unlocked": list(tools.STARTERS),
        "deepest_subnet": 0,
        "runs": 0,
        "wins": 0,
        "ids_evaded": 0,
        "tutorial": False,      # played through to the end at least once
        "fullscreen": False,
        "best_run": {},         # mode -> seconds for a full clear
        "best_solve": {},       # puzzle kind -> fastest solve in seconds
        "manual": {},           # field name -> {"example": str, "count": int}
        "signatures": {},            # signature name -> {"hex": str, "count": int}
    }


class Save:
    def __init__(self, path=None):
        self.path = path or default_path()
        self.data = _blank()
        self.load()

    def load(self):
        try:
            with open(self.path) as fh:
                loaded = json.load(fh)
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            # unreadable save: keep it aside rather than overwrite it
            try:
                os.replace(self.path, self.path + ".corrupt")
            except OSError:
                pass
            return
        if not isinstance(loaded, dict):
            return
        # saves from before the renames: ICE became IDS, and the tools got new names
        if "ice_kills" in loaded:
            loaded.setdefault("ids_evaded", loaded["ice_kills"])
        if "magic" in loaded:                       # MAGIC became CARVE, BREACH became PAYLOAD
            loaded.setdefault("signatures", loaded["magic"])
        if isinstance(loaded.get("best_solve"), dict):
            for old, new in (("MAGIC", "CARVE"), ("BREACH", "PAYLOAD")):
                if old in loaded["best_solve"]:
                    loaded["best_solve"].setdefault(new, loaded["best_solve"].pop(old))
        if isinstance(loaded.get("unlocked"), list):
            loaded["unlocked"] = [tools.RENAMED.get(d, d) for d in loaded["unlocked"]]
        for key, blank in self.data.items():
            if isinstance(loaded.get(key), type(blank)):
                self.data[key] = loaded[key]
        self.data["version"] = VERSION
        known = [d for d in self.data["unlocked"] if d in tools.TOOLS]
        self.data["unlocked"] = known + [d for d in tools.STARTERS if d not in known]

    def write(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(self.data, fh, indent=1, sort_keys=True)
        os.replace(tmp, self.path)

    # ---- progression
    def unlocked(self):
        return list(self.data["unlocked"])

    def unlock_next(self):
        """Unlock the next tool in line. Returns its id, or None if all are out."""
        for d in tools.UNLOCK_ORDER:
            if d not in self.data["unlocked"]:
                self.data["unlocked"].append(d)
                return d
        return None

    def learn_field(self, name, example):
        """Record a solved protocol field. True if it is new to the manual."""
        entry = self.data["manual"].get(name)
        if entry is None:
            self.data["manual"][name] = {"example": example, "count": 1}
            return True
        entry["count"] = entry.get("count", 0) + 1
        return False

    def learn_signature(self, name, hexbytes):
        entry = self.data["signatures"].get(name)
        if entry is None:
            self.data["signatures"][name] = {"hex": hexbytes, "count": 1}
            return True
        entry["count"] = entry.get("count", 0) + 1
        return False

    def record_solve(self, kind, seconds):
        best = self.data["best_solve"].get(kind)
        if best is None or seconds < best:
            self.data["best_solve"][kind] = round(seconds, 1)
            return True
        return False

    def record_ids_evaded(self):
        self.data["ids_evaded"] += 1
        return self.unlock_next()

    def record_run(self, mode, deepest_subnet, won, seconds):
        """Returns True if this was a new best full-clear time for the mode."""
        self.data["runs"] += 1
        self.data["deepest_subnet"] = max(self.data["deepest_subnet"], deepest_subnet)
        best = False
        if won:
            self.data["wins"] += 1
            prev = self.data["best_run"].get(mode)
            if prev is None or seconds < prev:
                self.data["best_run"][mode] = round(seconds, 1)
                best = True
        return best
