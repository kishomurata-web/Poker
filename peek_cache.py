"""Says what is in a collection cache, before anything long is run against it.

The exporters take --lines and --nodes filters, and a filter naming something
the cache does not contain quietly produces nothing. At a different stack depth
the flop bet that names a line is a different size, so 40BB's XC33 is not
guaranteed to exist at 20BB. This looks, so the export can be asked for once.

    python peek_cache.py turn_calib20\\cache
"""
import collections
import glob
import gzip
import json
import os
import sys


def peek(cache):
    files = sorted(glob.glob(os.path.join(cache, "*.jsonl")))
    if not files:
        sys.exit("no .jsonl files under %s" % cache)

    pairs, lines, nodes, boards = (collections.Counter() for _ in range(4))
    odd = []
    for p in files:
        name = os.path.basename(p)[: -len(".jsonl")]
        parts = name.split("__")
        if len(parts) != 4:
            odd.append(name)
            continue
        pair, board, line, node = parts
        pairs[pair] += 1
        lines[line] += 1
        nodes[node] += 1
        boards[board] += 1

    print("files            %d" % len(files))
    print("distinct boards  %d" % len(boards))
    if odd:
        print("unreadable names %d   e.g. %s" % (len(odd), odd[0]))
    for title, c in (("pairs", pairs), ("lines", lines), ("nodes", nodes)):
        print("\n%s (%d)" % (title, len(c)))
        for k, v in sorted(c.items()):
            print("    %-12s %5d files" % (k, v))

    # One record per (line, node) is enough to see the menu, which is what
    # decides how the sizes fold into the table's five columns.
    print("\naction menus")
    seen = set()
    for p in files:
        parts = os.path.basename(p)[: -len(".jsonl")].split("__")
        if len(parts) != 4:
            continue
        key = (parts[2], parts[3])
        if key in seen:
            continue
        try:
            with open(p, encoding="utf-8") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    rec = json.loads(raw)
                    acts = rec.get("actions") or []
                    pot = rec.get("pot")
                    fr = []
                    for a in acts:
                        if a == "X":
                            fr.append("X")
                        elif a == "RAI":
                            fr.append("AI")
                        elif a.startswith("R") and pot:
                            try:
                                fr.append("%d%%" % round(float(a[1:]) / float(pot) * 100))
                            except ValueError:
                                fr.append(a)
                        else:
                            fr.append(a)
                    has_ev = "evs" in rec
                    print("    %-10s %-12s pot %-8s %s%s" % (
                        parts[2], parts[3], pot, "  ".join(fr),
                        "" if has_ev else "   [no evs in record]"))
                    seen.add(key)
                    break
        except Exception as exc:                              # noqa: BLE001
            print("    %-10s %-12s unreadable: %s" % (parts[2], parts[3], exc))
            seen.add(key)

    print("\nsuggested filters")
    print("  --lines %s" % ",".join(sorted(lines)))
    print("  --nodes %s" % ",".join(sorted(nodes)))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    peek(sys.argv[1])
