"""Reduces a collection cache to one row per hand-strength bucket.

export_freqs.py answers "how often is this spot bet"; this answers "by which
hands", which is what tells a range bet from a polar one. The two are the same
pass over the same cache, split only by which combos are summed together.

The share is reach-weighted inside each bucket, so a bucket's numbers describe
the hands the player actually holds there rather than the hands they could.

    python export_hands.py --cache turn_calib_flops1755/cache --out hands40.csv.gz
    python export_hands.py --selftest

Columns:
    pair, line, node, board, card   as in export_freqs.py
    bucket   one of the seventeen in handbuckets.py
    combos   the size of this bucket in the acting player's range, in combos
    share    the bucket's share of that whole range, 0..1
    check, b33, b50, b75, b125
             the bucket's own mix over the five printed tiers, summing to 1.
             A bucket the player never holds here is written with an empty mix.
    c1..c5, f1..f5
             the five actions this bucket plays most, by their own codes, with
             their frequencies. The table's five tiers each cover more than one
             real size in most spots, and the app scores the size rather than
             the tier, so naming the size is worth a couple of points for no
             extra lines - but only if the size is known, which is what these
             carry. Fewer than five live actions leaves the rest blank.
"""
import argparse, csv, glob, gzip, json, os, sys

import handbuckets as HB
from export_freqs import decode_u16, as_float, action_frac

COMBOS = 1326
TIERS = ["check", "b33", "b50", "b75", "b125"]
TOP_N = 5

def tier_of(code, pot):
    """The five columns the strategy table prints, by share of pot."""
    if code == "X": return 0
    if code == "RAI": return 4
    f = action_frac(code, pot)
    if f is None: return 4
    if f < 0.36:  return 1
    if f < 0.605: return 2
    if f < 1.105: return 3
    if f < 1.755: return 4
    return 4

def by_bucket(rec, board):
    """[(bucket, combos, [5 tier frequencies])] for one decision."""
    actions = rec["actions"]
    n = len(actions)
    strat = decode_u16(rec["strategy"])
    reach = decode_u16(rec["reach"])
    if len(strat) != n * COMBOS or len(reach) != COMBOS:
        raise ValueError("record has %d strategy and %d reach entries, expected %d and %d"
                         % (len(strat), len(reach), n * COMBOS, COMBOS))
    table = HB.table(board)
    pot = rec.get("pot")
    slot = [tier_of(a, pot) for a in actions]
    nb = len(HB.BUCKETS)
    got = [0.0] * nb
    mix = [[0.0] * 5 for _ in range(nb)]
    per = [[0.0] * n for _ in range(nb)]        # per real action, not per tier
    for c in range(COMBOS):
        r = reach[c]
        if not r: continue
        b = table[c]
        if b < 0: continue
        got[b] += r
        for a in range(n):
            s = strat[a * COMBOS + c]
            if s: mix[b][slot[a]] += r * s; per[b][a] += r * s
    total = sum(got)
    out = []
    for b in range(nb):
        if got[b]:
            top = sorted(((per[b][a] / (got[b] * 10000.0), actions[a]) for a in range(n)),
                         reverse=True)[:TOP_N]
            out.append((HB.BUCKETS[b], got[b] / 10000.0, got[b] / total if total else 0.0,
                        [v / (got[b] * 10000.0) for v in mix[b]],
                        [(c, f) for f, c in top if f > 0]))
        else:
            out.append((HB.BUCKETS[b], 0.0, 0.0, None, []))
    return out

def rows_for_file(path, problems, lines, nodes, keep_empty=False):
    name = os.path.basename(path)[: -len(".jsonl")]
    parts = name.split("__")
    if len(parts) != 4: return
    pair, board, line, node = parts
    if (lines and line not in lines) or (nodes and node not in nodes): return
    flop = [board[i:i + 2] for i in range(0, 6, 2)]
    with open(path, encoding="utf-8") as fh:
        for n, raw in enumerate(fh, 1):
            raw = raw.strip()
            if not raw: continue
            try:
                rec = json.loads(raw)
                card = rec.get("card") or "-"
                cards = flop + ([card] if card != "-" else [])
                for bucket, combos, share, mix, top in by_bucket(rec, cards):
                    if mix is None and not keep_empty: continue
                    cols = ["", "", "", "", ""] if mix is None else \
                           [round(v, 4) for v in mix]
                    flat = []
                    for i in range(TOP_N):
                        flat += [top[i][0], round(top[i][1], 4)] if i < len(top) else ["", ""]
                    yield [pair, line, node, board, card, bucket,
                           round(combos, 4), round(share, 4)] + cols + flat
            except Exception as exc:                      # noqa: BLE001
                problems.append("%s line %d: %s" % (os.path.basename(path), n, exc))

def export(cache, out, lines, nodes, keep_empty=False):
    files = sorted(glob.glob(os.path.join(cache, "*.jsonl")))
    if not files: sys.exit("no .jsonl files under %s" % cache)
    problems, written = [], 0
    with gzip.open(out, "wt", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["pair", "line", "node", "board", "card", "bucket",
                    "combos", "share"] + TIERS +
                   [x for i in range(1, TOP_N + 1) for x in (f"c{i}", f"f{i}")])
        for i, p in enumerate(files, 1):
            for row in rows_for_file(p, problems, lines, nodes, keep_empty):
                w.writerow(row); written += 1
            if i % 500 == 0:
                print("  %d/%d files, %d rows" % (i, len(files), written), flush=True)
    print("wrote %s: %d rows from %d files" % (out, written, len(files)))
    if problems:
        print("skipped %d unreadable records:" % len(problems))
        for m in problems[:10]: print("   ", m)

def selftest():
    import base64, struct, zlib
    fails = []
    def check(name, got, want):
        if got == want: print("  ok   %s" % name)
        else: fails.append(name); print("  FAIL %s\n        got %r want %r" % (name, got, want))

    def enc(vals):
        raw = struct.pack("<%dH" % len(vals), *vals)
        return base64.b64encode(gzip.compress(raw)).decode()

    board = ["As", "Kh", "7d"]
    tbl = HB.table(board)
    top = [c for c, b in enumerate(tbl) if b == HB.BIDX["トップペア"]]
    air = [c for c, b in enumerate(tbl) if b == HB.BIDX["ノーペア"]]
    reach = [0] * COMBOS
    for c in top[:4]: reach[c] = 10000
    for c in air[:6]: reach[c] = 10000
    # two actions: check, and a third-pot bet. Top pair always bets, air checks.
    strat = [0] * (2 * COMBOS)
    for c in top[:4]: strat[COMBOS + c] = 10000
    for c in air[:6]: strat[c] = 10000
    # The cache writes actions as bare code strings - "X", "R2", "RAI" - which
    # is what export_freqs.py reads. An earlier version of this test used a
    # richer shape and so never exercised the code that reads them.
    rec = {"actions": ["X", "R2"],
           "pot": "6.100", "strategy": enc(strat), "reach": enc(reach)}
    res = {b: (combos, share, mix, top) for b, combos, share, mix, top in by_bucket(rec, board)}
    check("a bucket the player holds is sized in combos", res["トップペア"][0], 4.0)
    check("and carries its share of the range", round(res["トップペア"][1], 3), 0.4)
    check("top pair is all in the ~33% column", [round(v, 3) for v in res["トップペア"][2]],
          [0.0, 1.0, 0.0, 0.0, 0.0])
    check("air is all in the check column", [round(v, 3) for v in res["ノーペア"][2]],
          [1.0, 0.0, 0.0, 0.0, 0.0])
    check("a bucket never held is left empty", res["フルハウス"][2], None)
    check("and counts no combos", res["フルハウス"][0], 0.0)
    check("the shares add to the whole range",
          round(sum(r[1] for r in res.values()), 6), 1.0)
    check("every bucket's mix adds to one",
          all(abs(sum(r[2]) - 1) < 1e-6 for r in res.values() if r[2]), True)
    check("R2 into 6.1 lands in ~33%", tier_of("R2", "6.100"), 1)
    check("a half-pot bet lands in 50%", tier_of("R3.05", "6.100"), 2)
    check("a pot-sized bet lands in 75%", tier_of("R6.1", "6.100"), 3)
    check("an overbet lands in 125%~", tier_of("R9", "6.100"), 4)
    check("an all-in lands in 125%~", tier_of("RAI", "6.100"), 4)
    check("a check is a check", tier_of("X", "6.100"), 0)

    # End to end, through a real file on disk, because every failure so far has
    # been in the reading rather than in the sums.
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "UTG_vs_BB__AsKh7d__FLOP__flop_IP.jsonl")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
        problems = []
        rows = list(rows_for_file(p, problems, set(), set(), keep_empty=True))
        check("a cache file reads without complaint", problems, [])
        check("and yields one row per bucket", len(rows), len(HB.BUCKETS))
        held = list(rows_for_file(p, [], set(), set()))
        check("a bucket nobody holds is left out by default",
              len(held), sum(1 for r in rows if r[8] != ""))
        check("the spot is read off the filename",
              rows[0][:5], ["UTG_vs_BB", "FLOP", "flop_IP", "AsKh7d", "-"])
        top = next(r for r in rows if r[5] == "トップペア")
        check("top pair's row carries its mix", top[8:13], [0.0, 1.0, 0.0, 0.0, 0.0])
        air = next(r for r in rows if r[5] == "ノーペア")
        check("and air's row carries its own", air[8:13], [1.0, 0.0, 0.0, 0.0, 0.0])
        empty = next(r for r in rows if r[5] == "フルハウス")
        check("a bucket never held writes blanks", empty[8:13], ["", "", "", "", ""])
    check("and names no actions", empty[13:], [""] * (2 * TOP_N))
    check("top pair's real size is named", top[13:15], ["R2", 1.0])
    check("air's is too", air[13:15], ["X", 1.0])
    check("with nothing after the actions it plays", top[15:], [""] * (2 * TOP_N - 2))

    print("\n=== %d passed, %d failed ===" % (25 - len(fails), len(fails)))
    return 1 if fails else 0

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache")
    ap.add_argument("--out", default="hands40.csv.gz")
    ap.add_argument("--lines", default="")
    ap.add_argument("--nodes", default="")
    ap.add_argument("--all-buckets", action="store_true",
                    help="also write the buckets the range never holds here")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest: sys.exit(selftest())
    if not a.cache: sys.exit("--cache is required (or --selftest)")
    sp = lambda v: {x.strip() for x in v.split(",") if x.strip()}
    export(a.cache, a.out, sp(a.lines), sp(a.nodes), a.all_buckets)

if __name__ == "__main__":
    main()
