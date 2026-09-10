"""Reduces a collection cache to one row per action, small enough to send.

The cache is hundreds of megabytes of per-combo arrays. What a simplified
strategy is built from is one number per action per spot - the share of the
range that takes it - so that is all this writes out.

The share is reach-weighted, which is the only reading that means anything:
`strategy` is a per-combo frequency, and a combo the player never holds here
must not count the same as one they always hold.

    python export_freqs.py --cache turn_calib_flops1755/cache --out flop40.csv.gz
    python export_freqs.py --cache turn_calib/cache           --out turn40.csv.gz
    python export_freqs.py --selftest

Flop groups carry one record; turn groups carry one per turn card, and the card
is a column rather than a separate file.

Columns:
    pair    UTG_vs_BB, BTN_vs_BB, ...
    line    FLOP, or the flop line the turn was reached through (XC33, B50C, ...)
    node    flop_OOP / flop_IP, turn_OOP / turn_IP, turn_IP_vs20, ...
    board   the flop, as the site spells it, e.g. AsJh7s
    card    the turn card, or "-" on the flop
    pot     the pot the decision is made into, in big blinds
    combos  the size of the acting player's range here, in combos
    code    X, R2.35, RAI, ...
    frac    the bet as a fraction of the pot; empty for X, and for RAI, whose
            size the cache does not carry
    freq    0..1, the share of the range taking this action. The codes of one
            (pair, line, node, board, card) sum to 1.
"""

import argparse
import base64
import glob
import gzip
import json
import os
import struct
import sys
import tempfile

COMBOS = 1326


def decode_u16(b64):
    raw = gzip.decompress(base64.b64decode(b64))
    return struct.unpack("<%dH" % (len(raw) // 2), raw)


def as_float(v):
    """The cache carries the site's own JSON, where a pot is the string
    "6.100" rather than a number. Everything downstream divides by it."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def action_frac(code, pot):
    """The bet as a share of the pot. None where there is no size to divide:
    a check, and an all-in, whose absolute size the cache never carried."""
    if code in ("X", "C", "F") or code == "RAI":
        return None
    if code.startswith("R"):
        pot = as_float(pot)
        return round(float(code[1:]) / pot, 4) if pot else None
    raise ValueError("unknown action code %r" % code)


def frequencies(rec):
    """Reach-weighted share of the range per action, plus the range's size."""
    actions = rec["actions"]
    n = len(actions)
    strat = decode_u16(rec["strategy"])
    reach = decode_u16(rec["reach"])
    if len(strat) != n * COMBOS or len(reach) != COMBOS:
        raise ValueError("record has %d strategy and %d reach entries, expected %d and %d"
                         % (len(strat), len(reach), n * COMBOS, COMBOS))
    total = sum(reach)
    if not total:
        return None, 0.0
    # Most of the 1326 combos are not in the range here, and skipping them once
    # rather than per action is the difference between minutes and tens of them
    # over 21,060 groups.
    live = [c for c in range(COMBOS) if reach[c]]
    out = []
    for a in range(n):
        off = a * COMBOS
        acc = sum(reach[c] * strat[off + c] for c in live)
        out.append(acc / (total * 10000.0))
    return out, total / 10000.0


def rows_for_file(path, problems=None):
    """One (pair, board, line, node) group is one file, holding one record per
    card - a single "-" on the flop, and up to 48 turn cards otherwise.

    A record that cannot be read is noted and skipped rather than allowed to end
    the run: this reads tens of thousands of files written over days, and losing
    the other 20,000 groups to one truncated line would be the worse outcome."""
    name = os.path.basename(path)[: -len(".jsonl")]
    parts = name.split("__")
    if len(parts) != 4:
        return
    pair, board, line, node = parts
    seen = set()
    with open(path, encoding="utf-8") as fh:
        for n, raw in enumerate(fh, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
                card = rec.get("card") or "-"
                # A resumed run can append a second copy of a card it already
                # had. The first is as good as the last.
                if card in seen:
                    continue
                seen.add(card)
                freqs, combos = frequencies(rec)
                if freqs is None:
                    continue
                pot = as_float(rec.get("pot"))
                out = []
                for code, f in zip(rec["actions"], freqs):
                    frac = action_frac(code, pot)
                    out.append((pair, line, node, board, card, "%g" % pot,
                                "%.1f" % combos, code,
                                "" if frac is None else "%.4f" % frac, "%.6f" % f))
            except Exception as e:
                if problems is not None:
                    problems.append("%s line %d: %s" % (os.path.basename(path), n, e))
                continue
            for row in out:
                yield row


def export(cache, out):
    files = sorted(glob.glob(os.path.join(cache, "*.jsonl")))
    if not files:
        sys.exit("no .jsonl files in %s" % cache)
    opener = gzip.open if out.endswith(".gz") else open
    n_rows = 0
    boards = set()
    problems = []
    with opener(out, "wt", encoding="utf-8", newline="\n") as fh:
        fh.write("pair,line,node,board,card,pot,combos,code,frac,freq\n")
        for i, path in enumerate(files):
            for row in rows_for_file(path, problems):
                fh.write(",".join(row) + "\n")
                n_rows += 1
                boards.add(row[3])
            if (i + 1) % 2000 == 0:
                print("  %d/%d files (%d rows so far)" % (i + 1, len(files), n_rows))
    print("\nwrote %s" % out)
    print("  %d rows, %d boards, %d files read" % (n_rows, len(boards), len(files)))
    print("  %.1f MB" % (os.path.getsize(out) / 1e6))
    if problems:
        print("\n  %d record(s) could not be read and were skipped:" % len(problems))
        for p in problems[:10]:
            print("    " + p)
        if len(problems) > 10:
            print("    ... and %d more" % (len(problems) - 10))


# ---------------------------------------------------------------------------


def pack_u16(vals):
    return base64.b64encode(gzip.compress(struct.pack("<%dH" % len(vals), *vals))).decode()


def selftest():
    """The weighting is the whole point of this script, so it is checked
    against a case where the unweighted answer is different and wrong."""
    tmp = tempfile.mkdtemp(prefix="expfreq")
    cache = os.path.join(tmp, "cache")
    os.makedirs(cache)

    # Half the range is unreachable here. Its strategy is the opposite of the
    # reachable half's, so a mean that ignored reach would come out at 0.50.
    reach = [100] * 663 + [0] * 663
    strat_x = [2000] * 663 + [8000] * 663
    strat_b = [8000] * 663 + [2000] * 663
    rec = {
        # A string, because that is how the site writes it and how the cache
        # keeps it. A float here is what let this script ship dividing by a str.
        "card": "-", "pot": "6.100", "actions": ["X", "R2"],
        "reach": pack_u16(reach),
        "strategy": pack_u16(strat_x + strat_b),
        "evs": "",
    }
    with open(os.path.join(cache, "UTG_vs_BB__AsJh7s__FLOP__flop_IP.jsonl"),
              "w", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")

    # A turn group: two cards in one file, so the card has to come off the
    # record rather than the filename, and one file must not collapse to one row.
    turn = os.path.join(cache, "UTG_vs_BB__AsJh7s__XC33__turn_OOP.jsonl")
    with open(turn, "w", encoding="utf-8") as fh:
        for card, mix in (("2c", (3000, 7000)), ("Kd", (9000, 1000))):
            fh.write(json.dumps({
                "card": card, "pot": "12.200", "actions": ["X", "R4"],
                "reach": pack_u16([100] * COMBOS),
                "strategy": pack_u16([mix[0]] * COMBOS + [mix[1]] * COMBOS),
                "evs": "",
            }) + "\n")

    rows = list(rows_for_file(os.path.join(cache, "UTG_vs_BB__AsJh7s__FLOP__flop_IP.jsonl")))
    trows = list(rows_for_file(turn))
    failures = []

    def check(name, got, want):
        if got == want:
            print("  ok   %s" % name)
        else:
            print("  FAIL %s\n         got  %r\n         want %r" % (name, got, want))
            failures.append(name)

    check("one row per action", len(rows), 2)
    check("the pair, line, node and board come off the filename",
          rows[0][:4], ("UTG_vs_BB", "FLOP", "flop_IP", "AsJh7s"))
    check("a flop row has no card", rows[0][4], "-")
    check("the range is only the reachable half", rows[0][6], "6.6")
    check("a check has no pot fraction", rows[0][8], "")
    check("R2 into 6.1 is 33% of pot", rows[1][8], "0.3279")
    check("the check is weighted by reach, not counted flat", rows[0][9], "0.200000")
    check("and so is the bet", rows[1][9], "0.800000")
    check("the two sum to the whole range",
          round(float(rows[0][9]) + float(rows[1][9]), 6), 1.0)

    check("every turn card gets its own rows", len(trows), 4)
    check("and carries the card it was dealt",
          [r[4] for r in trows], ["2c", "2c", "Kd", "Kd"])
    check("each card keeps its own mix",
          [r[9] for r in trows], ["0.300000", "0.700000", "0.900000", "0.100000"])
    check("the turn line is read from the filename", trows[0][1], "XC33")

    # An all-in carries no size in the cache, so it must not be given one.
    check("an all-in has no pot fraction", action_frac("RAI", "6.100"), None)
    check("a pot written as a string still divides",
          action_frac("R2", "6.100"), 0.3279)
    check("and a missing pot does not raise", action_frac("R2", None), None)

    print("\n=== %d passed, %d failed ===" % (16 - len(failures), len(failures)))
    return 1 if failures else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", help="the flop sweep's cache folder")
    ap.add_argument("--out", default="flop_freqs.csv.gz")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(selftest())
    if not args.cache:
        sys.exit("--cache is required (or --selftest)")
    export(args.cache, args.out)


if __name__ == "__main__":
    main()
