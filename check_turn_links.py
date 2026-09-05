"""Reads the converted files and reports what the turn tree actually connects.

The conversion's own summary ran two unrelated questions together, and the
larger number was the one that did not matter:

  - Is there a defence node nothing points at?  That is a linking bug: the
    data was collected, converted, shipped to the phone, and is unreachable.
    It should be zero, and if it is not, the pot arithmetic in link_turn has
    stopped holding.

  - How many turn bets have defence data behind them?  That is a fact about
    the collection, not about the conversion. The collector took a subset of
    each turn menu on purpose - run_defence2.bat's own header is a table of
    reach per request, so the sizes it skipped were skipped deliberately -
    and every one of those correctly reads as "no data" in the app.

Reads postflop/<depth>/*.json.gz, so it answers both without re-converting.

    python check_turn_links.py [postflop/40]
"""

import collections
import glob
import gzip
import json
import os
import sys


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.join("postflop", "40")
    files = sorted(glob.glob(os.path.join(root, "*.json.gz")))
    if not files:
        sys.exit("no .json.gz files in %s" % root)
    print("reading %d files from %s\n" % (len(files), root))

    defence = 0
    pointed = 0
    orphans = []
    by_line = collections.defaultdict(lambda: [0, 0])   # line -> [linked, dead]
    by_size = collections.defaultdict(lambda: [0, 0])   # pot% -> [linked, dead]
    dead_examples = []

    for n, path in enumerate(files):
        with gzip.open(path) as fh:
            nodes = json.load(fh)["nodes"]
        targets = set()
        for key, node in nodes.items():
            parts = key.split("|")
            if len(parts) != 3 or not parts[1].startswith("turn_"):
                continue
            if parts[1] not in ("turn_OOP", "turn_IP"):
                continue
            for a in node["actions"]:
                if a["type"] not in ("BET", "RAISE"):
                    continue
                nxt = a.get("next")
                # An opening turn node has nothing to fold to, so every RAISE
                # on it is the first bet of the street.
                linked_here = bool(nxt) and nxt != "END"
                if linked_here:
                    targets.add(nxt)
                slot = 0 if linked_here else 1
                by_line[parts[0]][slot] += 1
                pot = node["pot"] or 0
                size = a.get("betsize")
                pct = ("all-in" if a.get("allin") or size is None
                       else "%d%%" % round(size / pot * 100) if pot else "?")
                by_size[pct][slot] += 1
                if not linked_here and len(dead_examples) < 8:
                    dead_examples.append("%s  %s  %s (%s of pot)"
                                         % (os.path.basename(path), key, a["code"], pct))
        for key, node in nodes.items():
            parts = key.split("|")
            if len(parts) == 3 and "_vs" in parts[1] and parts[1].startswith("turn_"):
                defence += 1
                if key in targets:
                    pointed += 1
                elif len(orphans) < 8:
                    orphans.append("%s  %s" % (os.path.basename(path), key))
        if (n + 1) % 50 == 0:
            print("  %d/%d files" % (n + 1, len(files)))

    print("\n=== linking (this is the one that can be broken) ===")
    print("  defence nodes            %d" % defence)
    print("  reachable from a bet     %d" % pointed)
    print("  ORPHANED                 %d" % (defence - pointed))
    if orphans:
        print("  first few:")
        for o in orphans:
            print("    " + o)
    else:
        print("  nothing collected is unreachable.")

    linked = sum(v[0] for v in by_line.values())
    dead = sum(v[1] for v in by_line.values())
    total = linked + dead
    print("\n=== coverage (this is how much was collected) ===")
    print("  turn bets with defence   %d of %d (%.1f%%)"
          % (linked, total, linked * 100.0 / max(1, total)))
    print("\n  by flop line:")
    for line in sorted(by_line, key=lambda k: -sum(by_line[k])):
        a, b = by_line[line]
        print("    %-8s %7d / %7d  (%.0f%%)" % (line, a, a + b, a * 100.0 / max(1, a + b)))
    print("\n  by bet size:")
    def order(k):
        return (1, 0) if k in ("all-in", "?") else (0, int(k.rstrip("%")))
    for size in sorted(by_size, key=order):
        a, b = by_size[size]
        print("    %-8s %7d / %7d  (%.0f%%)" % (size, a, a + b, a * 100.0 / max(1, a + b)))
    if dead_examples:
        print("\n  examples of a bet with no defence node:")
        for e in dead_examples:
            print("    " + e)


if __name__ == "__main__":
    main()
