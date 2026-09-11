"""The board vocabulary the strategy document is written in.

Kept to the terms already in use, so a new table reads in the same language as
the one it replaces; a few extra cuts are added where the data asked for them.
"""
import gto, collections

RV = gto.RV
RANKS = gto.RANKS
A = RV['A']

def windows():
    """Every five-consecutive-rank window, A counted high and low."""
    out = []
    for lo in range(0, 9):                       # 2-6 ... T-A
        out.append(set(range(lo, lo + 5)))
    out.append({A, RV['2'], RV['3'], RV['4'], RV['5']})   # the wheel
    return out
WINDOWS = windows()

def in_one_window(rs):
    s = set(rs)
    return any(s <= w for w in WINDOWS)

def sd(x, y):
    """Two ranks that can both sit inside one five-window."""
    return any({x, y} <= w for w in WINDOWS)

class Flop:
    def __init__(self, board, weight):
        self.board = board; self.w = weight
        cs = [(board[i], board[i+1]) for i in range(0, 6, 2)]
        self.r = sorted((RV[r] for r, _ in cs), reverse=True)
        self.s = [s for _, s in cs]
        self.hi, self.mid, self.lo = self.r
        self.sc = collections.Counter(self.s).most_common(1)[0][1]
        self.rc = collections.Counter(self.r).most_common(1)[0][1]

    # --- texture ---
    @property
    def paired(self):   return self.rc >= 2
    @property
    def trips(self):    return self.rc == 3
    @property
    def pair_is_hi(self): return self.paired and self.r[0] == self.r[1]
    @property
    def mono(self):     return self.sc == 3
    @property
    def twotone(self):  return self.sc == 2
    @property
    def rainbow(self):  return self.sc == 1
    @property
    def flush_made(self):  return self.mono          # three of a suit on the flop
    # --- straights ---
    @property
    def hmsd(self):     return sd(self.hi, self.mid)
    @property
    def mlsd(self):     return sd(self.mid, self.lo)
    @property
    def straight_made(self): return in_one_window(self.r) and not self.paired
    @property
    def three_run(self):
        r = self.r
        return r[0] == r[1] + 1 == r[2] + 2
    @property
    def wheel(self):
        wc = [x for x in self.r if x == A or x <= RV['5']]
        return len(wc) >= 2 and all(x <= RV['9'] for x in self.r if x != A)
    @property
    def wheel_made(self):  return self.wheel and self.hi == A and in_one_window(self.r)
    # --- counts ---
    @property
    def nT(self):       return sum(1 for x in self.r if x >= RV['T'])
    @property
    def gap_hm(self):   return self.hi - self.mid
    @property
    def gap_ml(self):   return self.mid - self.lo
