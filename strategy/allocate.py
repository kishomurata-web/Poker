"""Decides how many rules each spot is worth, for a table meant to be memorised.

Giving every spot the same number of rules spends the same effort on a spot
whose boards all play alike as on one that splits four ways. This scores each
spot at each rule count, then hands the next rule to whichever spot gains the
most score per line it adds, until the budget runs out.

    python allocate.py --flop flop40.csv.gz --turn turn40.csv.gz \
        --hands hands40.csv.gz --turn-hands turnhands40.csv.gz --budget 300

Writes alloc.json, which build.py reads with --alloc. Computing the curves
means growing every tree at every size, which takes a few minutes; --curves
caches them so a different budget costs nothing.
"""
import argparse, collections, csv, gzip, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gto, preds, turnpred, tree, turntree, maxscore

SIZES = [1, 2, 3, 4, 6, 8, 10]

def load_hands(path, keyed_on_card):
    H = collections.defaultdict(list)
    with gzip.open(path, 'rt') as f:
        for r in csv.DictReader(f):
            if r['check'] == '': continue
            c = float(r['combos'])
            if c <= 0: continue
            k = (r['pair'], r['line'], r['node'], r['board'])
            if keyed_on_card: k += (r['card'],)
            H[k].append((r['bucket'], c, [float(r[x]) for x in
                         ('check', 'b33', 'b50', 'b75', 'b125')]))
    return H

def spot_curve(rows, H, key, grow, wf):
    """-> {size: (score x weight, weight, rules, lines)} for one spot."""
    out = {}
    for n in SIZES:
        tot = w_all = 0.0; rules = lines = 0
        for rs, path in grow(rows, n):
            by = collections.defaultdict(list)
            for f, _ in rs:
                k = key + (f.board,) + ((f.card,) if hasattr(f, 'card') else ())
                for bucket, c, mix in H.get(k, []):
                    by[bucket].append((wf(f.w, c), mix))
            if not by: continue
            gs = maxscore.groups(by, [])
            rules += 1; lines += 1 + len(gs)
            for t, bks, wt, s in gs:
                tot += s * wt; w_all += wt
        out[n] = (tot, w_all, rules, lines)
    return out

def curves(a):
    F = {b: preds.Flop(b, w) for b, w in gto.WEIGHTS.items()}
    C = {}
    HF = load_hands(a.hands, False)
    sp = collections.defaultdict(list)
    for k, d in gto.read(a.flop): sp[k[:3]].append((F[k[3]], d))
    for k, rows in sp.items():
        C['F|' + '|'.join(k)] = spot_curve(
            rows, HF, k, lambda r, n: tree.grow(r, max_leaves=n, min_w=150, max_depth=3),
            lambda w, c: w * c)
    HT = load_hands(a.turn_hands, True)
    tsp = collections.defaultdict(list)
    for k, d in gto.read(a.turn): tsp[k[:3]].append((turnpred.Turn(k[3], k[4]), d))
    for k, rows in tsp.items():
        C['T|' + '|'.join(k)] = spot_curve(
            rows, HT, k, lambda r, n: turntree.grow(r, max_leaves=n, min_w=80, max_depth=3),
            lambda w, c: c)
    return C

def greedy(C, budget):
    cur = {k: SIZES[0] for k in C}
    def totals():
        s = w = l = r = 0.0
        for k, n in cur.items():
            t, ww, rr, ll = C[k][n]; s += t; w += ww; l += ll; r += rr
        return s / w * 100, int(r), int(l)
    while True:
        best = None
        for k, n in cur.items():
            i = SIZES.index(n)
            if i + 1 >= len(SIZES): continue
            n2 = SIZES[i + 1]
            t0, _, _, l0 = C[k][n]; t1, _, _, l1 = C[k][n2]
            if l1 <= l0: continue
            g = (t1 - t0) / (l1 - l0)
            if best is None or g > best[0]: best = (g, k, n2, l1 - l0)
        if best is None: break
        if totals()[2] + best[3] > budget: break
        cur[best[1]] = best[2]
    return cur, totals()

def main(a):
    if a.curves and os.path.exists(a.curves):
        C = {k: {int(n): v for n, v in c.items()}
             for k, c in json.load(open(a.curves)).items()}
        print(f"curves read from {a.curves}")
    else:
        C = curves(a)
        if a.curves:
            json.dump({k: {str(n): v for n, v in c.items()} for k, c in C.items()},
                      open(a.curves, 'w'))
            print(f"curves written to {a.curves}")
    cur, (s, r, l) = greedy(C, a.budget)
    json.dump(cur, open(a.out, 'w'), indent=1)
    print(f"{a.out}: {r} rules, {l} lines, score {s:.2f}%")
    n1 = sum(1 for v in cur.values() if v == 1)
    print(f"{n1} of {len(cur)} spots need one rule; the rest:")
    for k, n in sorted(cur.items(), key=lambda x: -x[1]):
        if n > 1: print(f"  {n:2d}  {k}")

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--flop', default='flop40.csv.gz')
    p.add_argument('--turn', default='turn40.csv.gz')
    p.add_argument('--hands', default='hands40.csv.gz')
    p.add_argument('--turn-hands', default='turnhands40.csv.gz')
    p.add_argument('--budget', type=int, default=300)
    p.add_argument('--curves', default='curves.json')
    p.add_argument('--out', default='alloc.json')
    main(p.parse_args())
