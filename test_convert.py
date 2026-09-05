"""Checks that postflop_convert.py wires the turn up the way the app walks it.

The bug this guards against shipped once already: every turn bet was written
with no successor, so the collected defence nodes went into the files and the
app answered every bet on the turn with "no data". Nothing failed - the
conversion succeeded, the nodes were present, and only the pointers were
missing - so the test asserts on the pointers rather than on the run.

Builds a tiny cache by hand instead of reading the real one. The real cache is
several GB and lives on the collecting PC; the shapes that matter here (a bet
that lands on a defence node, an all-in with no size, a bet whose node was
never collected) are all expressible in a few records.

    python test_convert.py
"""

import base64
import gzip
import json
import os
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PAIR = "BTN_vs_BB"
FLOP = "3h3d2s"
# check_opens works the open back out of the pot: (pot - dead) / 2, with 1.5
# dead for BTN vs BB. A pot of 6.1 is the 2.3 open the defaults assume, so the
# converter accepts the folder instead of refusing it.
FLOP_POT = 6.1

failures = []


def check(name, got, want):
    if got == want:
        print("  ok   %s" % name)
    else:
        print("  FAIL %s\n         got  %r\n         want %r" % (name, got, want))
        failures.append(name)


def pack_u16(vals):
    return base64.b64encode(gzip.compress(struct.pack("<%dH" % len(vals), *vals))).decode()


def pack_f32(vals):
    return base64.b64encode(gzip.compress(struct.pack("<%df" % len(vals), *vals))).decode()


def record(card, pot, actions):
    n = len(actions)
    return {
        "card": card,
        "pot": pot,
        "actions": actions,
        "reach": pack_u16([100] * 1326),
        "strategy": pack_u16([10000 // n] * (n * 1326)),
        "evs": pack_f32([1.0] * (n * 1326)),
    }


def write(cache, line, node, recs):
    path = os.path.join(cache, "%s__%s__%s__%s.jsonl" % (PAIR, FLOP, line, node))
    with open(path, "w", encoding="utf-8") as fh:
        for r in recs:
            fh.write(json.dumps(r) + "\n")


def build_cache(cache):
    os.makedirs(cache)
    # Flop: only enough for the converter to have a tree at all.
    write(cache, "FLOP", "flop_OOP", [record("-", FLOP_POT, ["X"])])
    write(cache, "FLOP", "flop_IP", [record("-", FLOP_POT, ["X", "R2"])])
    write(cache, "FLOP", "flop_OOP_vs33", [record("-", 8.1, ["F", "C"])])

    # Turn, line XC33, card Kc. OOP opens for 20% or 50% of a 10.1 pot; the
    # node each bet reaches carries the pot it made, and nothing in the names
    # says which action leads where.
    write(cache, "XC33", "turn_OOP", [record("Kc", 10.1, ["X", "R2.02", "R5.05"])])
    write(cache, "XC33", "turn_IP", [record("Kc", 10.1, ["X", "R3.333"])])
    write(cache, "XC33", "turn_IP_vs20", [record("Kc", 12.12, ["F", "C", "R6"])])
    write(cache, "XC33", "turn_IP_vs50", [record("Kc", 15.15, ["F", "C"])])
    write(cache, "XC33", "turn_OOP_vs33", [record("Kc", 13.433, ["F", "C"])])

    # An all-in. The cache stores no size for it, so the pot cannot place it;
    # with one bet and one defence node left over the pairing is forced.
    write(cache, "XC50", "turn_OOP", [record("2h", 8.0, ["X", "RAI"])])
    write(cache, "XC50", "turn_IP", [record("2h", 8.0, ["X"])])
    write(cache, "XC50", "turn_IP_vs125", [record("2h", 18.0, ["F", "C"])])

    # A bet whose defence was never collected. This is the case the app has to
    # keep reporting as "no data" rather than being made to guess at.
    write(cache, "XC75", "turn_OOP", [record("7d", 9.0, ["X", "R3.0"])])
    write(cache, "XC75", "turn_IP", [record("7d", 9.0, ["X"])])


def nxt(nodes, key, code):
    for a in nodes[key]["actions"]:
        if a["code"] == code:
            return a["next"]
    return "<no such action: %s>" % code


def main():
    tmp = tempfile.mkdtemp(prefix="convtest")
    cache = os.path.join(tmp, "cache")
    build_cache(cache)
    sizes = os.path.join(tmp, "_sizes.json")
    with open(sizes, "w", encoding="utf-8") as fh:
        json.dump({"depth": 40.125,
                   "resolved": {PAIR: {"pot": FLOP_POT, "c33": "R2"}}}, fh)

    out = os.path.join(tmp, "out")
    run = subprocess.run(
        [sys.executable, os.path.join(HERE, "postflop_convert.py"),
         "--cache", cache, "--sizes", sizes, "--out", out],
        capture_output=True, text=True)
    if run.returncode != 0:
        print(run.stdout)
        print(run.stderr)
        sys.exit("postflop_convert.py failed")
    print(run.stdout.rstrip() + "\n")

    path = os.path.join(out, "40", "%s__%s.json.gz" % (PAIR, FLOP))
    with gzip.open(path) as fh:
        nodes = json.load(fh)["nodes"]

    print("turn defence pointers")
    check("OOP's 20% reaches IP facing 20%",
          nxt(nodes, "XC33|turn_OOP|Kc", "R2.02"), "XC33|turn_IP_vs20|Kc")
    check("OOP's 50% reaches IP facing 50%",
          nxt(nodes, "XC33|turn_OOP|Kc", "R5.05"), "XC33|turn_IP_vs50|Kc")
    check("a check still reaches IP",
          nxt(nodes, "XC33|turn_OOP|Kc", "X"), "XC33|turn_IP|Kc")
    check("IP's 33% reaches OOP facing 33%",
          nxt(nodes, "XC33|turn_IP|Kc", "R3.333"), "XC33|turn_OOP_vs33|Kc")

    print("\nterminals")
    check("a checked-through turn ends the hand",
          nxt(nodes, "XC33|turn_IP|Kc", "X"), "END")
    check("calling a turn bet ends the hand",
          nxt(nodes, "XC33|turn_IP_vs20|Kc", "C"), "END")
    check("folding to a turn bet ends the hand",
          nxt(nodes, "XC33|turn_IP_vs20|Kc", "F"), "END")
    check("a raise over a turn bet has no node",
          nxt(nodes, "XC33|turn_IP_vs20|Kc", "R6"), None)

    print("\nthe awkward cases")
    check("an all-in is placed by elimination",
          nxt(nodes, "XC50|turn_OOP|2h", "RAI"), "XC50|turn_IP_vs125|2h")
    check("an uncollected defence stays uncollected",
          nxt(nodes, "XC75|turn_OOP|7d", "R3.0"), None)

    print("\nthe flop is unchanged")
    check("IP's cbet still reaches OOP facing it",
          nxt(nodes, "FLOP|flop_IP", "R2"), "FLOP|flop_OOP_vs33")
    check("calling the cbet still opens the turn",
          nxt(nodes, "FLOP|flop_OOP_vs33", "C"), "TURN:XC33")

    print("\nthe run says what it did")
    # The number that would mean this script is broken, kept apart from the one
    # that only means the collector was selective.
    check("every collected node is reported reachable",
          "turn defence: 4 of 4 collected nodes are reachable" in run.stdout, True)
    check("an uncollected bet is reported as coverage, not as a fault",
          "4 of 5 turn bets lead to one (80%)" in run.stdout, True)
    check("and no warning is raised for it",
          "WARNING" in run.stdout, False)
    check("it reports the all-in it inferred",
          "1 all-in placed by elimination" in run.stdout, True)

    print("\n=== %d passed, %d failed ===" % (16 - len(failures), len(failures)))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
