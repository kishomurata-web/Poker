"""Reads the per-bucket export and says what shape a board's strategy has.

Which buckets a board even offers varies - a trips board has no top pair - so
the shape is read at fixed slices of the range ordered by made strength rather
than at fixed buckets. That lets two boards be compared to each other at all.

The cut points between the four shapes are a judgement, not a feature of the
data: the spread, the sag and the dip are all continuous across the 1755
boards with no gap to put a line in. They are parameters for that reason.
"""
import csv, gzip, collections

BUCKETS = ['ストフラ・4カード', 'フルハウス', 'フラッシュ', 'ストレート', '3カード', '2ペア',
           'オーバーペア', 'トップペア', '2nd-3rdペア', '最下位ペア以下',
           'コンボドロー', 'ナッツFD', 'FD', 'OESD', 'ガットショット', '2BDFD', 'ノーペア']

BANDS = [(0.00, 0.05), (0.05, 0.15), (0.15, 0.40), (0.40, 1.00)]
BAND_NAMES = ['ナッツ', '強', '中', '弱']
PATTERNS = ['レンジベット', 'デポラー', 'ポラー', '標準']

THRESHOLDS = {
    'A': dict(flat=20, high=55, dep=5,  pol=5),
    'B': dict(flat=15, high=60, dep=10, pol=10),
    'C': dict(flat=10, high=65, dep=15, pol=15),
}

def load(path):
    """(pair, line, node, board, card) -> {bucket: (combos, betfreq)}.

    The card belongs in the key even though it is always "-" on the flop: on
    the turn one board carries 49 of them, and leaving it out silently keeps
    only the last.

    Only the combo count and the chance of betting survive; the split between
    sizes is already in the table's five columns.
    """
    out = collections.defaultdict(dict)
    with gzip.open(path, 'rt') as f:
        for r in csv.DictReader(f):
            if r['check'] == '': continue
            c = float(r['combos'])
            if c <= 0: continue
            out[(r['pair'], r['line'], r['node'], r['board'], r['card'])][r['bucket']] = \
                (c, 1.0 - float(r['check']))
    return out

def bands(counts):
    """counts: {bucket: (combos, betfreq)} -> bet rate at each of the four bands."""
    seq = [(counts[b][0], counts[b][1]) for b in BUCKETS if b in counts]
    tot = sum(c for c, _ in seq)
    if tot <= 0: return None
    out, pos = [], 0.0
    for lo, hi in BANDS:
        a = w = 0.0
        pos = 0.0
        for c, bp in seq:
            s, e = pos / tot, (pos + c) / tot
            pos += c
            ov = max(0.0, min(e, hi) - max(s, lo))
            if ov > 0: a += ov * bp; w += ov
        out.append(a / w if w else None)
    return out if all(x is not None for x in out) else None

def merge(per_board):
    """per_board: [(weight, {bucket: (combos, betfreq)})] -> one combined count.

    A board that comes down six times as often as another has six times the say,
    which is the same weighting the printed frequencies use.
    """
    acc = collections.defaultdict(lambda: [0.0, 0.0])
    for w, counts in per_board:
        for b, (c, bp) in counts.items():
            a = acc[b]; a[0] += w * c; a[1] += w * c * bp
    return {b: (a[0], a[1] / a[0]) for b, a in acc.items() if a[0] > 0}

def classify(bd, t):
    b = [x * 100 for x in bd]
    if max(b) - min(b) <= t['flat'] and sum(b) / 4 >= t['high']: return 'レンジベット'
    if b[1] - b[0] >= t['dep']: return 'デポラー'
    if min(b[0], b[3]) - b[2] >= t['pol']: return 'ポラー'
    return '標準'

def describe(bd):
    return '/'.join(str(round(x * 100)) for x in bd)
