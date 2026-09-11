"""Rounds a printed line to multiples of ten without letting it drift.

Rounding each number on its own breaks the total, and fixing the total
afterwards by nudging the largest entry is not the closest line to the real
strategy. This searches all five entries together, against the boards
themselves rather than against their average, so the printed line is the one
that sits closest to the hands it will actually be played on.
"""
import gto

STEP = 10
VALUES = list(range(0, 101, STEP))

def best(members, tiers5):
    """members: [(weight, [5 true frequencies])] -> the closest legal line."""
    cost = [[sum(w * abs(v / 100.0 - f[i]) for w, f in members) for v in VALUES]
            for i in range(5)]
    NEG = float('inf')
    # dp[i][t] = cheapest way to fill slots i.. with t percent left to spend
    dp = [[NEG] * 101 for _ in range(6)]
    pick = [[None] * 101 for _ in range(6)]
    dp[5][0] = 0.0
    for i in range(4, -1, -1):
        for t in range(0, 101, STEP):
            bestc, bestv = NEG, None
            for vi, v in enumerate(VALUES):
                if v > t: break
                c = cost[i][vi] + dp[i + 1][t - v]
                if c < bestc: bestc, bestv = c, v
            dp[i][t], pick[i][t] = bestc, bestv
    out, t = [], 100
    for i in range(5):
        v = pick[i][t]; out.append(v); t -= v
    return out

def line5(m):
    return [m['X'], m['S'], m['M'], m['L'], m['XL'] + m['OB']]

def round_leaf(rows):
    members = [(f.w, line5({t: d.get(t, 0.0) for t in gto.TIERS})) for f, d in rows]
    return best(members, None)
