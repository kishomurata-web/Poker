"""Picks the one action to play, for a table meant to be scored rather than
to describe a range.

The app grades a hand's choice against that hand's own most frequent action, so
naming one action per board class is graded on every hand in that class,
including the hands whose own best answer is the opposite. Splitting the class
by hand strength first is what recovers most of that; the action inside each
group is searched rather than taken to be the group's most frequent one,
because the two differ whenever a group's hands disagree.
"""
import csv, gzip, collections
import score

TIER_COLS = ('check', 'b33', 'b50', 'b75', 'b125')
TIER_NAMES = ('check', '~33%', '50%', '75%', '125%~')

def rows(path, weight):
    """Yields (row, weight, five tier frequencies) for every bucket held."""
    with gzip.open(path, 'rt') as fh:
        for r in csv.DictReader(fh):
            if r['check'] == '': continue
            c = float(r['combos'])
            if c <= 0: continue
            yield r, weight(r) * c, [float(r[k]) for k in TIER_COLS]

def best_action(members):
    """members: [(weight, mix)] -> (tier index, expected score, never mass)."""
    best = None
    for t in range(5):
        s = nv = w = 0.0
        for wt, mix in members:
            M = max(mix)
            v = score.score_of(mix[t], M)
            if v is None: nv += wt
            else: s += wt * v
            w += wt
        if not w: continue
        if best is None or s / w > best[1]: best = (t, s / w, nv / w)
    return best

def groups(by_bucket, order):
    """{bucket: [(w, mix)]} -> [(tier index, [buckets], weight, score)], biggest first."""
    g = collections.defaultdict(lambda: [[], 0.0, 0.0])
    for bk, mem in by_bucket.items():
        b = best_action(mem)
        if b is None: continue
        w = sum(x for x, _ in mem)
        e = g[b[0]]; e[0].append((w, bk)); e[1] += w; e[2] += w * b[1]
    out = []
    for t, (bks, w, s) in g.items():
        bks.sort(key=lambda x: order.index(x[1]) if x[1] in order else 99)
        out.append((t, [b for _, b in bks], w, s / w if w else 0.0))
    out.sort(key=lambda x: -x[2])
    return out
