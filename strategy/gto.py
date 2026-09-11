"""Reads an exported frequency CSV and puts every bet into one of five tiers.

The tiers are the ones the strategy table is written in. The site runs two
different sizing menus - SB vs BB gets 12/25/50/75/100/150%, the other five
pairs get 20/33/55/83/125% - and both have to land in the same five columns,
so the cut points sit in the gaps that separate the two menus rather than on
any one menu's sizes.
"""
import csv, gzip, json, os, collections

RANKS = '23456789TJQKA'
RV = {r: i for i, r in enumerate(RANKS)}
WEIGHTS = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      'flop_weights.json')))

TIERS = ['X', 'S', 'M', 'L', 'XL', 'OB']   # XL and OB share the printed 125%~ column
TIER_LABEL = {'X': 'check', 'S': '~33%', 'M': '50%', 'L': '75%',
              'XL': '125%~', 'OB': '125%~ (overbet/all-in)'}

def tier(code, frac):
    if code == 'X':   return 'X'
    if code == 'RAI': return 'OB'
    f = float(frac)
    if f < 0.36:  return 'S'      # 10, 12, 15, 20, 25, 33%
    if f < 0.605: return 'M'      # 40, 50, 55%
    if f < 1.105: return 'L'      # 75, 83, 100%
    if f < 1.755: return 'XL'     # 125, 150%
    return 'OB'                   # 200%, all-in

def read(path, want=None):
    """Yields ((pair, line, node, board, card), {tier: freq}).

    Rows arrive grouped by spot, so one decision is assembled from the run of
    rows that share a key rather than by holding the whole file.
    """
    cur, acc = None, collections.defaultdict(float)
    with gzip.open(path, 'rt') as f:
        for r in csv.DictReader(f):
            k = (r['pair'], r['line'], r['node'], r['board'], r['card'])
            if k != cur:
                if cur and (want is None or cur[:3] in want): yield cur, dict(acc)
                cur, acc = k, collections.defaultdict(float)
            acc[tier(r['code'], r['frac'])] += float(r['freq'])
    if cur and (want is None or cur[:3] in want): yield cur, dict(acc)

def wmean(pairs):
    tw = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / tw if tw else 0.0
