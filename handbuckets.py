"""Which of the seventeen strength buckets a hand falls in on a given board.

The buckets are read off what the hole cards contribute, not off the best five
cards: on K K 7 a hand of A 2 has a pair in the five-card sense, but it is
playing the board's pair, and counting it as a pair would hide exactly the
thing these buckets exist to show.

Draws split the no-pair bucket only. A hand that made a pair keeps its pair
bucket however well it draws, which keeps each bucket a statement about made
strength and leaves the draw labels to mean what they say.
"""
import collections, functools

RANKS = '23456789TJQKA'
RV = {r: i for i, r in enumerate(RANKS)}
SUITS = 'cdhs'
CARDS = [r + s for r in RANKS for s in SUITS]
CARD_IDX = {c: i for i, c in enumerate(CARDS)}

# Same order the cache's per-combo arrays use, verified in postflop_convert.py
# against a real response: hand_info "Ad4c" lands on index 1184.
COMBOS = [(CARDS[a], CARDS[b]) for b in range(52) for a in range(b)]
assert len(COMBOS) == 1326

MADE = ['ストフラ・4カード', 'フルハウス', 'フラッシュ', 'ストレート', '3カード',
        '2ペア', 'オーバーペア', 'トップペア', '2nd-3rdペア', '最下位ペア以下']
DRAW = ['コンボドロー', 'ナッツFD', 'FD', 'OESD', 'ガットショット', '2BDFD', 'ノーペア']
BUCKETS = MADE + DRAW
BIDX = {b: i for i, b in enumerate(BUCKETS)}

@functools.lru_cache(maxsize=None)
def _straight_high_key(key):
    return _straight_scan(key)

def _straight_high(ranks):
    """Highest card of a five-straight inside these ranks, or None.

    Keyed on the distinct ranks, which repeat heavily across the 1326 combos of
    one board - the straight maths is the hot path of the whole export."""
    return _straight_high_key(tuple(sorted(set(ranks))))

def _straight_scan(ranks):
    s = set(ranks)
    if RV['A'] in s: s.add(-1)                     # the wheel
    best = None
    for hi in range(12, 2, -1):
        if all(hi - i in s for i in range(5)):
            best = hi; break
    if best is None and all(x in s for x in (-1, 0, 1, 2, 3)):
        best = 3
    return best

def _completing_ranks(known, hole_r):
    return _completing_key(tuple(sorted(set(known))), tuple(sorted(set(hole_r))))

@functools.lru_cache(maxsize=None)
def _completing_key(known, hole_r):
    """Ranks that would finish a straight, counting only straights that use a
    hole card - a board-only draw is not this hand's draw."""
    out = set()
    for r in range(13):
        if r in known: continue
        hi = _straight_high(list(known) + [r])
        if hi is None: continue
        need = set(range(hi - 4, hi + 1)) if hi >= 3 else {-1, 0, 1, 2, 3}
        need = {x if x >= 0 else RV['A'] for x in need}
        if need & set(hole_r): out.add(r)
    return out

def bucket(h1, h2, board):
    """h1, h2: 'Ad' style. board: list of 3 or 4 of them. -> bucket name."""
    hr = [RV[h1[0]], RV[h2[0]]]
    hs = [h1[1], h2[1]]
    br = [RV[c[0]] for c in board]
    bs = [c[1] for c in board]
    ar, asu = hr + br, hs + bs
    cnt = collections.Counter(ar)
    suits = collections.Counter(asu)
    hole = set(hr)

    # --- categories that need a hole card to be the hand's, not the board's ---
    flush_suit = next((s for s, n in suits.items() if n >= 5), None)
    if flush_suit and flush_suit in hs:
        fr = [RV[c[0]] for c in ([h1, h2] + board) if c[1] == flush_suit]
        if _straight_high(fr) is not None: return 'ストフラ・4カード'
    quad = [r for r, n in cnt.items() if n == 4 and r in hole]
    if quad: return 'ストフラ・4カード'
    trip_r = [r for r, n in cnt.items() if n >= 3]
    pair_r = [r for r, n in cnt.items() if n >= 2]
    if trip_r and len(pair_r) >= 2 and any(r in hole for r in pair_r):
        return 'フルハウス'
    if flush_suit and flush_suit in hs: return 'フラッシュ'
    if _straight_high(ar) is not None and _straight_high(br) is None:
        # the straight has to run through a hole card
        for r in hole:
            if _straight_high([x for x in ar if x != r] + [r]) is not None and \
               _straight_high([x for x in br]) is None:
                return 'ストレート'
    if any(r in hole for r in trip_r): return '3カード'
    mine = [r for r in pair_r if r in hole]
    if len(mine) >= 2 or (len(mine) == 1 and len(pair_r) >= 2): return '2ペア'
    if mine:
        r = mine[0]
        top = max(br)
        if hr[0] == hr[1]:                          # a pocket pair
            if r > top: return 'オーバーペア'
            if r < min(br): return '最下位ペア以下'
            return '2nd-3rdペア'
        if r == top: return 'トップペア'
        return '2nd-3rdペア'

    # --- no pair: read the draw ---
    fd = next((s for s, n in suits.items() if n == 4 and s in hs), None)
    nut = False
    if fd:
        higher = [RV[c[0]] for c in board if c[1] == fd]
        mine_s = [RV[c[0]] for c in (h1, h2) if c[1] == fd]
        blocked = set(higher) | set(mine_s)
        top_missing = max((r for r in range(13) if r not in blocked), default=-1)
        nut = bool(mine_s) and max(mine_s) > top_missing
    comp = _completing_ranks(set(ar), hr)
    sd = 'OESD' if len(comp) >= 2 else ('ガットショット' if len(comp) == 1 else None)
    if fd and sd: return 'コンボドロー'
    if fd: return 'ナッツFD' if nut else 'FD'
    if sd: return sd
    if hs[0] == hs[1] and suits[hs[0]] == 3: return '2BDFD'
    return 'ノーペア'

def table(board):
    """Bucket index for every one of the 1326 combos on this board."""
    dead = set(board)
    out = [-1] * 1326
    for i, (a, b) in enumerate(COMBOS):
        if a in dead or b in dead: continue
        out[i] = BIDX[bucket(a, b, board)]
    return out
