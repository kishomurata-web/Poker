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
    grid = collections.Counter()          # (pair, line) -> files
    spots = collections.Counter()         # (pair, line, node) -> boards
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
        grid[(pair, line)] += 1
        spots[(pair, line, node)] += 1

    print("files            %d" % len(files))
    print("distinct boards  %d" % len(boards))
    if odd:
        print("unreadable names %d   e.g. %s" % (len(odd), odd[0]))
    for title, c in (("pairs", pairs), ("lines", lines), ("nodes", nodes)):
        print("\n%s (%d)" % (title, len(c)))
        for k, v in sorted(c.items()):
            print("    %-12s %5d files" % (k, v))

    # A line that exists in the cache but only for some pairs is the failure
    # the totals above hide: the export names one filter for every pair, and
    # the pairs that do not carry that line come out empty without a word.
    # Only the lines that are not there for everyone are worth the space.
    print("\npairs x lines   (files; '-' means the pair does not have that line)")
    ps = sorted(pairs)
    partial = [ln for ln in sorted(lines)
               if sum(1 for pr in ps if grid[(pr, ln)]) not in (0, len(ps))]
    whole = [ln for ln in sorted(lines) if ln not in partial]
    if whole:
        print("    every pair has: %s" % ", ".join(whole))
    if not partial:
        print("    no line is missing for only some pairs")
    else:
        print("    %-12s %s" % ("", "  ".join("%10s" % p for p in ps)))
        for ln in partial:
            print("    %-12s %s" % (ln, "  ".join(
                "%10s" % (grid[(pr, ln)] or "-") for pr in ps)))

    # What an export asking for these lines would actually produce, spot by
    # spot. This is the number to compare against the CSV afterwards.
    print("\nturn spots that exist   (pair, line, node -> boards)")
    tn = sorted({k for k in spots if k[2].startswith("turn_") and "_vs" not in k[2]})
    if not tn:
        print("    none - this cache holds no turn nodes")
    for pr, ln, nd in tn:
        print("    %-12s %-12s %-10s %5d" % (pr, ln, nd, spots[(pr, ln, nd)]))

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

    # An all-in's own size is not in the actions list, so whether it can be
    # priced against the pot depends on what else the record carries. At 40BB
    # filing it with the overbets was safe; at 20BB a pot near the starting
    # stack leaves an all-in that may be under half of it.
    print("\nfields on one record")
    for p in files[:1]:
        try:
            with open(p, encoding="utf-8") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    rec = json.loads(raw)
                    for k in sorted(rec):
                        v = rec[k]
                        if isinstance(v, str) and len(v) > 40:
                            show = "<%d chars>" % len(v)
                        else:
                            show = repr(v)[:70]
                        print("    %-14s %s" % (k, show))
                    break
        except Exception as exc:                              # noqa: BLE001
            print("    unreadable: %s" % exc)

    print("\nsuggested filters")
    print("  --lines %s" % ",".join(sorted(lines)))
    print("  --nodes %s" % ",".join(sorted(nodes)))


def find(root=".", max_depth=3):
    """Folders under here that hold .jsonl files, so the path need not be known."""
    root = os.path.abspath(root)
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        depth = dirpath[len(root):].count(os.sep)
        if depth >= max_depth:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames if not d.startswith((".", "__", "node_modules"))]
        n = sum(1 for f in filenames if f.endswith(".jsonl"))
        if n:
            hits.append((n, os.path.relpath(dirpath, root)))
    return sorted(hits, reverse=True)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        hits = find()
        if not hits:
            sys.exit("no folder holding .jsonl files under %s" % os.path.abspath("."))
        print("caches found here:\n")
        for n, path in hits:
            print("    %-52s %7d files" % (path, n))
        print("\nrun it again naming one, e.g.\n    python peek_cache.py %s" % hits[0][1])
        sys.exit(0)
    peek(sys.argv[1])
