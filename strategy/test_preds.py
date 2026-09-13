"""Checks the board vocabulary means what the table says it means.

    python strategy/test_preds.py

Both bugs this guards against came from the same place: a set of two ranks
collapses to one element when the ranks are equal, and every window holding
that element then contains the "pair". A paired board was reported as three
to a straight on the half that was the pair.
"""
import collections
import sys

import gto
import preds


def flop(b):
    return preds.Flop(b, 1.0)


CASES = [
    # Paired at the top: HM is the pair, so not a straight connection at all;
    # ML is 7-4, inside one window.
    ('7h7d4c', 'hmsd', False), ('7h7d4c', 'mlsd', True),
    # Paired at the bottom: ML is the pair; HM is K-7, too far apart.
    ('Kh7d7c', 'hmsd', False), ('Kh7d7c', 'mlsd', False),
    # Paired at the bottom with a live HM: K-Q is inside one window.
    ('KhQdQc', 'hmsd', True), ('KhQdQc', 'mlsd', False),
    # Unpaired and connected: both halves are real.
    ('9h8d7c', 'hmsd', True), ('9h8d7c', 'mlsd', True),
    # A22 is two ranks, not three to a wheel.
    ('Ac2d2h', 'wheel', True), ('Ac2d2h', 'wheel_made', False),
    ('Ac3d2h', 'wheel_made', True),
]


def main():
    bad = 0
    n = 0

    for board, attr, want in CASES:
        got = bool(getattr(flop(board), attr))
        n += 1
        if got != want:
            bad += 1
            print('FAIL  %-8s %-12s got %s, want %s' % (board, attr, got, want))

    # The property that started this: on a paired board one of HM and ML is
    # always the pair, so the two can never both be true.
    F = [preds.Flop(b, w) for b, w in gto.WEIGHTS.items()]
    paired = [f for f in F if f.paired]
    for name, count in (('HM,MLSD', sum(1 for f in paired if f.hmsd and f.mlsd)),
                        ('wheel_made', sum(1 for f in paired if f.wheel_made)),
                        ('straight_made', sum(1 for f in paired if f.straight_made))):
        n += 1
        if count:
            bad += 1
            print('FAIL  %d of %d paired boards report %s'
                  % (count, len(paired), name))

    # Unpaired boards are untouched by either fix.
    n += 1
    got = sum(1 for f in F if not f.paired and f.hmsd and f.mlsd)
    if got != 670:
        bad += 1
        print('FAIL  unpaired HM,MLSD is %d, want 670' % got)

    print('%d checks, %d failed' % (n, bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
