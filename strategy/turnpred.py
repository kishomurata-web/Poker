"""The same vocabulary, extended to the four cards a turn decision sees."""
import gto, preds, collections
RV = gto.RV
A = RV['A']
W = preds.WINDOWS

class Turn:
    def __init__(self, board, card, weight=1.0):
        self.w = weight
        f = [(board[i], board[i+1]) for i in range(0, 6, 2)]
        self.fr = sorted((RV[r] for r, _ in f), reverse=True)
        self.fs = [s for _, s in f]
        self.tr = RV[card[0]]; self.ts = card[1]
        self.hi, self.mid, self.lo = self.fr
        self.all_r = sorted(self.fr + [self.tr], reverse=True)
        self.all_s = self.fs + [self.ts]
        self.sc = collections.Counter(self.all_s)
        self.fsc = collections.Counter(self.fs)

    # flop shape
    @property
    def flop_paired(self):  return len(set(self.fr)) < 3
    @property
    def flop_mono(self):    return max(self.fsc.values()) == 3
    @property
    def flop_rain(self):    return max(self.fsc.values()) == 1
    @property
    def flop_str(self):     return (not self.flop_paired) and preds.in_one_window(self.fr)
    @property
    def gap_hm(self):       return self.hi - self.mid
    @property
    def gap_ml(self):       return self.mid - self.lo
    # board through the turn
    @property
    def paired_now(self):   return len(set(self.all_r)) < 4
    @property
    def turn_pairs(self):   return (not self.flop_paired) and self.tr in self.fr
    @property
    def flush_made(self):   return max(self.sc.values()) >= 3
    @property
    def turn_flush(self):   return (not self.flop_mono) and max(self.fsc.values()) == 2 \
                                   and self.sc[self.ts] == 3
    @property
    def fourth_suit(self):  return self.flop_mono and self.sc[self.ts] == 4
    @property
    def fd_on_rainbow(self):return self.flop_rain and self.sc[self.ts] == 2
    @property
    def overcard(self):     return self.tr > self.hi
    @property
    def pairs_hi(self):     return self.tr == self.hi
    @property
    def pairs_lo(self):     return self.tr == self.lo
    @property
    def nT(self):           return sum(1 for x in self.all_r if x >= RV['T'])
    @property
    def run3(self):
        u = sorted(set(self.all_r))
        return any(u[i] + 1 == u[i+1] and u[i] + 2 == u[i+2] for i in range(len(u) - 2))
    @property
    def four_straight(self):
        u = set(self.all_r)
        return len(u) == 4 and preds.in_one_window(u)
