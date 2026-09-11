"""Weight of each flop the cache names = how many of the 22,100 real flops it
stands for.

Derived by enumerating all 22,100 and canonicalising, rather than by counting
suit patterns by hand, so the weights are exact by construction. The cache
spells a flop with its own suit labels, so a spelling is matched to a class by
relabelling it rather than by string equality.

    python weights.py flop40.csv.gz          # rewrites flop_weights.json
"""
import csv, gzip, itertools, collections, json, os, sys

RANKS = '23456789TJQKA'
SUITS = 'shdc'
RV = {r: i for i, r in enumerate(RANKS)}

def canon(cards):
    best = None
    for perm in itertools.permutations(SUITS):
        m = dict(zip(SUITS, perm))
        t = sorted(((r, m[s]) for r, s in cards), key=lambda c: (-RV[c[0]], SUITS.index(c[1])))
        sp = ''.join(r + s for r, s in t)
        if best is None or sp < best: best = sp
    return best

def parse(b):
    return [(b[i], b[i + 1]) for i in range(0, 6, 2)]

def main(src):
    deck = [(r, s) for r in RANKS for s in SUITS]
    w = collections.Counter()
    for combo in itertools.combinations(deck, 3):
        w[canon(list(combo))] += 1
    with gzip.open(src, 'rt') as f:
        seen = sorted({r['board'] for r in csv.DictReader(f)})
    out = {b: w[canon(parse(b))] for b in seen}
    assert len(out) == 1755 and sum(out.values()) == 22100, 'not a complete flop set'
    dst = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'flop_weights.json')
    json.dump(out, open(dst, 'w'))
    print(f"{len(out)} flops, {sum(out.values())} combinations -> {dst}")

if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'flop40.csv.gz')
