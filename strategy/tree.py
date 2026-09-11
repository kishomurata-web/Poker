"""Grows one rule tree per spot, in the vocabulary the document already uses.

Conditions are carried as structured constraints rather than as sentences, so
two cuts on the same quantity collapse into one interval and a rule reads as a
person would write it. A split that does not change the printed line is undone.
"""
import gto, collections
RV = gto.RV
RANKS = 'AKQJT98765432'

# numeric families: (label, renderer bounds)
NUM = {
    'nT':  ('T以上が', lambda v: str(v), '枚'),
    'hi':  ('hi ', lambda v: RANKS[12 - v], ''),
    'mid': ('mid ', lambda v: RANKS[12 - v], ''),
    'lo':  ('lo ', lambda v: RANKS[12 - v], ''),
    'ghm': ('hi-mid差 ', lambda v: str(v), ''),
    'gml': ('mid-lo差 ', lambda v: str(v), ''),
}
BOOL = {
    'pair':  ('ペアボード', 'ペアなし'),
    'pairhi':('ハイカードがペア', 'ハイカード以外がペア'),
    'mono':  ('モノトーン', 'モノトーン以外'),
    'rain':  ('レインボー', 'レインボー以外'),
    'hmsd':  ('HMSD', 'HMnSD'),
    'mlsd':  ('MLSD', 'MLnSD'),
    'hmml':  ('HM,MLSD', 'HM,MLnSD'),
    'str':   ('ストレート完成', 'ストレート未完成'),
    'wheel': ('ホイールボード', 'ホイール以外'),
    'wmade': ('ホイール完成', 'ホイール未完成'),
    'run3':  ('3連続カード', '3連続カードなし'),
}

def candidates():
    C = []
    for k, fn in [('pair', lambda f: f.paired), ('pairhi', lambda f: f.pair_is_hi),
                  ('mono', lambda f: f.mono), ('rain', lambda f: f.rainbow),
                  ('hmsd', lambda f: f.hmsd), ('mlsd', lambda f: f.mlsd),
                  ('hmml', lambda f: f.hmsd and f.mlsd),
                  ('str', lambda f: f.straight_made), ('wheel', lambda f: f.wheel),
                  ('wmade', lambda f: f.wheel_made), ('run3', lambda f: f.three_run)]:
        C.append((k, None, None, fn))
    get = {'nT': lambda f: f.nT, 'hi': lambda f: f.hi, 'mid': lambda f: f.mid,
           'lo': lambda f: f.lo, 'ghm': lambda f: f.gap_hm, 'gml': lambda f: f.gap_ml}
    rng = {'nT': range(1, 4), 'hi': range(RV['5'], RV['A'] + 1), 'mid': range(0, 13),
           'lo': range(0, 13), 'ghm': range(0, 9), 'gml': range(0, 9)}
    for fam, g in get.items():
        for v in rng[fam]:
            C.append((fam, v, g, None))
    return C
CAND = candidates()

def test(c, f):
    fam, v, g, fn = c
    return fn(f) if fn else (g(f) >= v)

def stats(rows):
    tw = sum(f.w for f, d in rows)
    m = {t: sum(d.get(t, 0.0) * f.w for f, d in rows) / tw for t in gto.TIERS}
    return tw, m

def sse(rows):
    tw, m = stats(rows)
    return sum(f.w * sum((d.get(t, 0.0) - m[t]) ** 2 for t in gto.TIERS) for f, d in rows)

def vec5(m):
    raw = [m['X'], m['S'], m['M'], m['L'], m['XL'] + m['OB']]
    v = [round(x * 100) for x in raw]
    d = 100 - sum(v)
    if d: v[max(range(5), key=lambda i: raw[i])] += d
    return v

def grow(rows, max_leaves=10, min_w=150, max_depth=3, min_gain=1e-4, min_split=4):
    leaves = [(rows, [])]
    while len(leaves) < max_leaves:
        best = None
        for i, (rs, path) in enumerate(leaves):
            if len(rs) < 2: continue
            fams = {p[0] for p in path}
            if len(fams) >= max_depth: continue
            base = sse(rs)
            for c in CAND:
                fam, v, g, fn = c
                if fn and fam in fams: continue
                A = [(f, d) for f, d in rs if test(c, f)]
                B = [(f, d) for f, d in rs if not test(c, f)]
                if not A or not B: continue
                if sum(f.w for f, _ in A) < min_w or sum(f.w for f, _ in B) < min_w: continue
                gg = base - sse(A) - sse(B)
                if best is None or gg > best[0]: best = (gg, i, c, A, B)
        if best is None or best[0] < min_gain: break
        gg, i, c, A, B = best
        rs, path = leaves.pop(i)
        fam, v, g, fn = c
        leaves.append((A, path + [(fam, True, v)]))
        leaves.append((B, path + [(fam, False, v)]))
    # undo any split whose two sides would print near-enough the same line
    changed = True
    while changed:
        changed = False
        byparent = collections.defaultdict(list)
        for idx, (rs, path) in enumerate(leaves):
            if path: byparent[tuple(path[:-1])].append(idx)
        for par, idxs in byparent.items():
            if len(idxs) != 2: continue
            a, b = idxs
            va, vb = vec5(stats(leaves[a][0])[1]), vec5(stats(leaves[b][0])[1])
            if sum(abs(x - y) for x, y in zip(va, vb)) / 2 < min_split:
                merged = (leaves[a][0] + leaves[b][0], list(par))
                for j in sorted(idxs, reverse=True): leaves.pop(j)
                leaves.append(merged); changed = True; break
    return leaves

def label(path):
    bools, nums = [], collections.defaultdict(lambda: [None, None])
    for fam, pos, v in path:
        if fam in BOOL:
            bools.append(BOOL[fam][0 if pos else 1])
        else:
            b = nums[fam]
            if pos: b[0] = v if b[0] is None else max(b[0], v)
            else:   b[1] = v - 1 if b[1] is None else min(b[1], v - 1)
    ORD = ['pair','pairhi','mono','rain','hmsd','mlsd','hmml','str','wheel','wmade','run3']
    bools.sort(key=lambda w: min((i for i, k in enumerate(ORD)
               for lab in BOOL[k] if lab == w), default=99))
    words = list(bools)
    for fam, (lo, hi) in nums.items():
        pre, r, suf = NUM[fam]
        if fam in ('hi', 'mid', 'lo'):
            if lo is not None and hi is not None:
                words.append(f"{pre}{r(hi)}〜{r(lo)}" if hi != lo else f"{pre}{r(lo)}")
            elif lo is not None: words.append(f"{pre}{r(lo)}以上")
            else:                words.append(f"{pre}{r(hi)}以下")
        else:
            if lo is not None and hi is not None:
                words.append(f"{pre}{r(lo)}{suf}" if lo == hi else f"{pre}{r(lo)}〜{r(hi)}{suf}")
            elif lo is not None: words.append(f"{pre}{r(lo)}{suf}以上")
            else:                words.append(f"{pre}{r(hi)}{suf}以下")
    s = set(words)
    if {'モノトーン以外', 'レインボー以外'} <= s:
        words = [w for w in words if w not in ('モノトーン以外', 'レインボー以外')] + ['2トーン']
    return '　'.join(words) if words else '全ボード'

def fmt(leaves, scale=1.0):
    out = []
    for rs, path in leaves:
        tw, m = stats(rs)
        out.append((tw, label(path), vec5(m), round(tw * scale)))
    out.sort(reverse=True, key=lambda x: x[0])
    return out
