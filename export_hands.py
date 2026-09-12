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
    menu     every action available here, in the order the solver lists them,
             joined by "|". It repeats down the file and costs almost nothing
             compressed, and it is what makes the columns below readable
             without a second file to line them up against.
    f1..f10  this bucket's frequency for each action of the menu, in that order
    l1..l10  the EV it gives up by taking that action instead of the best one,
             in the solution's own units, averaged over the bucket weighted by
             reach. Zero for the actions the solver plays here.

             Frequency and EV loss answer different questions. The app scores
             frequency and never looks at EV inside the strategy, so a table
             built to score checks ranges the solver bets a third of the time -
             the check is the most common action for every hand class, and
             being most common is all the score asks. EV loss is what says
             whether that costs anything.
"""
import argparse, base64, csv, glob, gzip, json, os, struct, sys

import handbuckets as HB
from export_freqs import decode_u16, as_float, action_frac


def decode_f32(b64):
    raw = gzip.decompress(base64.b64decode(b64))
    return struct.unpack("<%df" % (len(raw) // 4), raw)

COMBOS = 1326
TIERS = ["check", "b33", "b50", "b75", "b125"]
MAX_ACT = 10

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

def ev_loss(evs, n):
    """Per combo, what each action gives up against that combo's best action.

    Only per combo does this mean anything: on a spade board Qs9s and Qh9h sit
    in the same bucket but not behind the same best action.
    """
    best = [max(evs[a * COMBOS + h] for a in range(n)) for h in range(COMBOS)]
    return [[best[h] - evs[a * COMBOS + h] for h in range(COMBOS)] for a in range(n)]


def by_bucket(rec, board):
    """[(bucket, combos, [5 tier frequencies])] for one decision."""
    actions = rec["actions"]
    n = len(actions)
    strat = decode_u16(rec["strategy"])
    reach = decode_u16(rec["reach"])
    evs = decode_f32(rec["evs"]) if "evs" in rec else None
    loss = ev_loss(evs, n) if evs and len(evs) == n * COMBOS else None
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
    lost = [[0.0] * n for _ in range(nb)]
    for c in range(COMBOS):
        r = reach[c]
        if not r: continue
        b = table[c]
        if b < 0: continue
        got[b] += r
        for a in range(n):
            s = strat[a * COMBOS + c]
            if s: mix[b][slot[a]] += r * s; per[b][a] += r * s
            if loss: lost[b][a] += r * loss[a][c]
    total = sum(got)
    out = []
    for b in range(nb):
        if got[b]:
            out.append((HB.BUCKETS[b], got[b] / 10000.0, got[b] / total if total else 0.0,
                        [v / (got[b] * 10000.0) for v in mix[b]],
                        [per[b][a] / (got[b] * 10000.0) for a in range(n)],
                        [lost[b][a] / got[b] for a in range(n)] if loss else None))
        else:
            out.append((HB.BUCKETS[b], 0.0, 0.0, None, None, None))
    return out

def trim(v, places):
    v = round(v, places)
    return 0 if v == 0 else v


def rows_for_file(path, problems, lines, nodes, keep_empty=False, pairs=None):
    name = os.path.basename(path)[: -len(".jsonl")]
    parts = name.split("__")
    if len(parts) != 4: return
    pair, board, line, node = parts
    if (lines and line not in lines) or (nodes and node not in nodes): return
    if pairs and pair not in pairs: return
    flop = [board[i:i + 2] for i in range(0, 6, 2)]
    with open(path, encoding="utf-8") as fh:
        for n, raw in enumerate(fh, 1):
            raw = raw.strip()
            if not raw: continue
            try:
                rec = json.loads(raw)
                card = rec.get("card") or "-"
                cards = flop + ([card] if card != "-" else [])
                menu = "|".join(rec["actions"])
                for bucket, combos, share, mix, freqs, losses in by_bucket(rec, cards):
                    if mix is None and not keep_empty: continue
                    cols = ["", "", "", "", ""] if mix is None else \
                           [round(v, 4) for v in mix]
                    # EV loss is carried to a thousandth, which is the
                    # precision the site itself keeps it at, and exact zeros
                    # are written as one character: most actions the solver
                    # plays give up nothing, so those cells are most of the file
                    fs = [trim(freqs[i], 4) if freqs and i < len(freqs) else ""
                          for i in range(MAX_ACT)]
                    ls = [trim(losses[i], 3) if losses and i < len(losses) else ""
                          for i in range(MAX_ACT)]
                    yield [pair, line, node, board, card, bucket,
                           round(combos, 4), round(share, 4)] + cols + [menu] + fs + ls
            except Exception as exc:                      # noqa: BLE001
                problems.append("%s line %d: %s" % (os.path.basename(path), n, exc))

def export(cache, out, lines, nodes, keep_empty=False, pairs=None):
    files = sorted(glob.glob(os.path.join(cache, "*.jsonl")))
    if not files: sys.exit("no .jsonl files under %s" % cache)
    problems, written = [], 0
    with gzip.open(out, "wt", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["pair", "line", "node", "board", "card", "bucket",
                    "combos", "share"] + TIERS + ["menu"] +
                   [f"f{i}" for i in range(1, MAX_ACT + 1)] +
                   [f"l{i}" for i in range(1, MAX_ACT + 1)])
        for i, p in enumerate(files, 1):
            for row in rows_for_file(p, problems, lines, nodes, keep_empty, pairs):
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

    def encf(vals):
        raw = struct.pack("<%df" % len(vals), *vals)
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
    # Top pair gives up 2bb by checking; air gives up 1bb by betting. Both are
    # playing their own best action, so both should come out at no loss.
    evs = [0.0] * (2 * COMBOS)
    for c in top[:4]: evs[c] = -2.0
    for c in air[:6]: evs[COMBOS + c] = -1.0
    rec = {"actions": ["X", "R2"], "pot": "6.100",
           "strategy": enc(strat), "reach": enc(reach), "evs": encf(evs)}
    res = {b: (combos, share, mix, fs, ls)
           for b, combos, share, mix, fs, ls in by_bucket(rec, board)}
    check("a bucket the player holds is sized in combos", res["トップペア"][0], 4.0)
    check("and carries its share of the range", round(res["トップペア"][1], 3), 0.4)
    check("top pair is all in the ~33% column", [round(v, 3) for v in res["トップペア"][2]],
          [0.0, 1.0, 0.0, 0.0, 0.0])
    check("air is all in the check column", [round(v, 3) for v in res["ノーペア"][2]],
          [1.0, 0.0, 0.0, 0.0, 0.0])
    check("top pair's frequencies follow the menu", [round(v, 3) for v in res["トップペア"][3]],
          [0.0, 1.0])
    check("and it gives up nothing by betting", [round(v, 3) for v in res["トップペア"][4]],
          [2.0, 0.0])
    check("air gives up nothing by checking", [round(v, 3) for v in res["ノーペア"][4]],
          [0.0, 1.0])
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
        check("every row names the menu it is read against", top[13], "X|R2")
        check("top pair's frequencies sit under the menu", top[14:16], [0.0, 1.0])
        check("and the rest of the ten are blank", top[16:24], [""] * 8)
        check("its EV loss sits under the same menu", top[24:26], [2.0, 0.0])
        check("air gives up nothing by checking", air[24:26], [0.0, 1.0])

    print("\n=== %d passed, %d failed ===" % (27 - len(fails), len(fails)))
    return 1 if fails else 0

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache")
    ap.add_argument("--out", default="hands40.csv.gz")
    ap.add_argument("--lines", default="")
    ap.add_argument("--nodes", default="")
    ap.add_argument("--pairs", default="",
                    help="comma-separated pairs to keep, e.g. UTG_vs_BB,BTN_vs_BB. "
                         "Splits one export into several smaller files when the "
                         "whole thing will not travel.")
    ap.add_argument("--all-buckets", action="store_true",
                    help="also write the buckets the range never holds here")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest: sys.exit(selftest())
    if not a.cache: sys.exit("--cache is required (or --selftest)")
    sp = lambda v: {x.strip() for x in v.split(",") if x.strip()}
    export(a.cache, a.out, sp(a.lines), sp(a.nodes), a.all_buckets, sp(a.pairs))

if __name__ == "__main__":
    main()
