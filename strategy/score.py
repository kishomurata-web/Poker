"""What the app would score a strategy built from this table.

The app scores one hand's decision: the chosen action's frequency FOR THAT HAND
against that hand's most frequent action. Playing the modal action every time
scores 1; mixing the way the solver mixes scores less than that, because every
draw from the mix that is not the modal action scores its share of it.
"""
import sys; sys.path.insert(0, '/home/user/Poker/strategy')
import gto, pattern

FREQ_MIN = 0.001      # index.html: FREQ_MIN = 10, out of 10000
MIX_SHARE = 0.1

def score_of(f, M):
    if M <= 0: return None
    if f >= M: return 1.0
    if f >= MIX_SHARE * M: return f / M
    if f >= FREQ_MIN: return 0.0
    return None            # 'never' - needs the EV loss the export does not carry

def mixed(mix):
    """Expected score for drawing from `mix` when `mix` is also the truth."""
    M = max(mix)
    tot = nev = 0.0
    for f in mix:
        s = score_of(f, M)
        if s is None: nev += f
        else: tot += f * s
    return tot, nev

def modal(mix):
    """Always take the most frequent action."""
    return 1.0, 0.0
