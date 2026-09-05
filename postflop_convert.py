"""Turns the crawler's cache into data files the training app can load.

    python postflop_convert.py [--cache DIR] [--out DIR] [--combos]

Reads turn_calib/cache/*.jsonl and writes one gzipped JSON per (pair, flop)
plus an index.json, so the app fetches ~1 file per hand instead of holding the
whole tree in memory. The cache is several GB; a single embedded blob the way
the preflop app does it is not an option here.

Each node carries an explicit `next` pointer per action rather than letting the
app re-derive poker flow. The collected tree is deliberately sparse - a donk
bet, an uncollected bet size, or a raise over a turn bet has no follow-up node
- and an explicit pointer makes "we have no data past here" a fact in the data
instead of a rule the app has to reimplement and keep in sync.
"""

import argparse
import base64
import datetime
import gzip
import json
import os
import struct
import sys
from collections import defaultdict

RANKS_ASC = "23456789TJQKA"
RANKS_DESC = "AKQJT98765432"
SUITS = "cdhs"

CARDS = [r + s for r in RANKS_ASC for s in SUITS]
CARD_IDX = {c: i for i, c in enumerate(CARDS)}

# Verified against a real response: hand_info "Ad4c" lands on index 1184 and
# every per-combo array agrees there.
COMBOS = []
for _b in range(52):
    for _a in range(_b):
        COMBOS.append((CARDS[_a], CARDS[_b]))
assert len(COMBOS) == 1326


def hand_class(c1, c2):
    r1, s1 = c1[0], c1[1]
    r2, s2 = c2[0], c2[1]
    if r1 == r2:
        return r1 + r2
    hi, lo = (r1, r2) if RANKS_DESC.index(r1) < RANKS_DESC.index(r2) else (r2, r1)
    return hi + lo + ("s" if s1 == s2 else "o")


HAND_ORDER = []
for i, hr in enumerate(RANKS_DESC):
    for j, cr in enumerate(RANKS_DESC):
        if i == j:
            HAND_ORDER.append(hr + hr)
        elif i < j:
            HAND_ORDER.append(hr + cr + "s")
        else:
            HAND_ORDER.append(cr + hr + "o")
HAND_INDEX = {h: i for i, h in enumerate(HAND_ORDER)}
assert len(HAND_ORDER) == 169

# Kept only so make_fake_cache.py can build ranges that switch whole classes
# on and off; the app owns the class mapping now.
COMBO_CLASS_IDX = [HAND_INDEX[hand_class(a, b)] for a, b in COMBOS]

# The preflop line each pair sits behind. The app matches the hand it just
# dealt against these strings to decide whether postflop data exists, so a
# wrong open size here does not produce wrong data - it produces an app where
# postflop silently never starts.
#
# The open size is written with a `*` and filled in from _sizes.json, which the
# collector stamps with the size it actually used. Hard-coding 2.3 was right
# while 40bb was the only depth; at 20bb it is a different number, and the
# failure mode is invisible.
PAIR_LINES = {
    "UTG_vs_BB": {"preflop": "R*-F-F-F-F-F-F-C", "oop": "BB", "ip": "UTG"},
    "BTN_vs_BB": {"preflop": "F-F-F-F-F-R*-F-C", "oop": "BB", "ip": "BTN"},
    "UTG_vs_BTN": {"preflop": "R*-F-F-F-F-C-F-F", "oop": "UTG", "ip": "BTN"},
    "SB_vs_BB": {"preflop": "F-F-F-F-F-F-R*-C", "oop": "SB", "ip": "BB"},
    "UTG_vs_SB": {"preflop": "R*-F-F-F-F-F-C-F", "oop": "SB", "ip": "UTG"},
    "BTN_vs_SB": {"preflop": "F-F-F-F-F-R*-C-F", "oop": "SB", "ip": "BTN"},
}
# What 40bb used, for a _sizes.json written before the collector recorded it.
DEFAULT_OPENS = {k: ("R3.5" if k == "SB_vs_BB" else "R2.3") for k in PAIR_LINES}


def pairs_with_opens(opens):
    out = {}
    for key, line in PAIR_LINES.items():
        code = (opens or {}).get(key) or DEFAULT_OPENS[key]
        out[key] = dict(line, preflop=line["preflop"].replace("R*", code))
    return out


PAIRS = pairs_with_opens(None)

# Which turn line each flop continuation leads into, and which flop node each
# non-terminal flop action leads to. Mirrors turn_calib.js's LINES/flopNodes.
LINES = ["XX", "XC33", "XC50", "XC75", "XR33C", "XR50C", "XC20",
         "B20C", "B33C", "B50C", "B75C"]


def decode_u16(b64):
    raw = gzip.decompress(base64.b64decode(b64))
    return struct.unpack("<%dH" % (len(raw) // 2), raw)


def decode_f32(b64):
    raw = gzip.decompress(base64.b64decode(b64))
    return struct.unpack("<%df" % (len(raw) // 4), raw)


def action_meta(code, pot):
    """Rebuild the bits of an action the app needs. The cache stores only the
    code, but type and size follow from it unambiguously."""
    if code == "X":
        return {"code": code, "type": "CHECK", "betsize": 0.0, "allin": False, "frac": 0.0}
    if code == "C":
        return {"code": code, "type": "CALL", "betsize": 0.0, "allin": False, "frac": 0.0}
    if code == "F":
        return {"code": code, "type": "FOLD", "betsize": 0.0, "allin": False, "frac": 0.0}
    if code == "RAI":
        return {"code": code, "type": "RAISE", "betsize": None, "allin": True, "frac": None}
    if code.startswith("R"):
        size = float(code[1:])
        return {
            "code": code, "type": "RAISE", "betsize": size, "allin": False,
            # betsize_by_pot is not in the cache, but pot is, and the code
            # carries the absolute size - checked against the live menus
            # (pot 6.1, R2 -> 33%, R3.35 -> 55%).
            "frac": round(size / pot, 4) if pot else None,
        }
    raise ValueError("unknown action code %r" % code)


def pack_u16(values):
    return base64.b64encode(gzip.compress(struct.pack("<%dH" % len(values), *values), 9)).decode("ascii")


def aggregate(rec):
    """Packs a node's per-combo arrays for the app.

    Everything stays at combo resolution (1326) and the app does the 169-class
    aggregation itself. Aggregating here meant this file and the app each had
    to enumerate the 169 classes in the same order, and they did not: the app
    uses GTO Wizard's own order (22, 32o, 32s, 33, ...) while this script had
    invented a grid order (AA, AKs, AQs, ...). Every hand read another hand's
    row. Combo indices have exactly one definition, verified against a real
    response, so there is nothing left to disagree about - and per-combo data
    is what the app needs anyway to tell Kh Qh apart from Ks Qs.
    """
    actions = rec["actions"]
    n = len(actions)
    strat = decode_u16(rec["strategy"])
    evs = decode_f32(rec["evs"])
    reach = decode_u16(rec["reach"])
    assert len(strat) == n * 1326 and len(evs) == n * 1326 and len(reach) == 1326

    # EV given up per combo, relative to that combo's own best action. This is
    # what a choice is graded against, and it only means anything per combo:
    # on a spade board Qs9s and Qh9h share a class but not a best action.
    best_ev = [0.0] * 1326
    for h in range(1326):
        b = evs[h]
        for a in range(1, n):
            e = evs[a * 1326 + h]
            if e > b:
                b = e
        best_ev[h] = b

    loss = []
    for a in range(n):
        off = a * 1326
        for h in range(1326):
            loss.append(min(65535, max(0, round((best_ev[h] - evs[off + h]) * 1000))))

    return {
        "reach": pack_u16([min(10000, max(0, v)) for v in reach]),
        "strat": pack_u16([min(10000, max(0, v)) for v in strat]),
        "loss": pack_u16(loss),
    }


def build_tree(sizes):
    """Explicit successor for every action of every flop node, plus which turn
    line each completed flop line feeds. Keys match the cache's group naming.

    Every size is optional. At 40bb the three cbet sizes were always on the
    menu, so c33/c50/c75 could be read straight out of the dict; at 20bb they
    cannot - UTG vs SB tops out at 55% of pot and SB vs BB's IP menu is only
    25% and 50%. A missing size here would have been a KeyError partway through
    a 25-minute convert, which is the good outcome; the bad one is a node keyed
    on the string "None" that the app then never matches.
    """
    r33, r50 = sizes.get("raise33"), sizes.get("raise50")
    t = {
        "FLOP|flop_OOP": {"X": "FLOP|flop_IP"},
        "FLOP|flop_IP": {"X": "TURN:XX"},
    }
    # IP's cbet sizes: each leads to OOP facing that bet, which leads to a line.
    for key, node, line in (("c20", "flop_OOP_vs20", "XC20"),
                            ("c33", "flop_OOP_vs33", "XC33"),
                            ("c50", "flop_OOP_vs50", "XC50"),
                            ("c75", "flop_OOP_vs75", "XC75")):
        size = sizes.get(key)
        if not size:
            continue
        t["FLOP|flop_IP"][size] = "FLOP|" + node
        t["FLOP|" + node] = {"C": "TURN:" + line, "F": "END"}
    # Check-raises hang off the node that faces the cbet being raised, so they
    # only exist if that cbet does.
    if r33 and "FLOP|flop_OOP_vs33" in t:
        t["FLOP|flop_OOP_vs33"][r33] = "FLOP|flop_IP_vs_raise33"
        t["FLOP|flop_IP_vs_raise33"] = {"C": "TURN:XR33C", "F": "END"}
    if r50 and "FLOP|flop_OOP_vs50" in t:
        t["FLOP|flop_OOP_vs50"][r50] = "FLOP|flop_IP_vs_raise50"
        t["FLOP|flop_IP_vs_raise50"] = {"C": "TURN:XR50C", "F": "END"}
    # OOP betting straight out. Where OOP is the preflop raiser this is the
    # c-bet; at 20bb BTN vs SB also offers SB a donk, which is the same shape
    # in the data and hangs off the same actions.
    for key, node, line in (("b20", "flop_IP_vs_bet20", "B20C"),
                            ("b33", "flop_IP_vs_bet33", "B33C"),
                            ("b50", "flop_IP_vs_bet50", "B50C"),
                            ("b75", "flop_IP_vs_bet75", "B75C")):
        size = sizes.get(key)
        if not size:
            continue
        t["FLOP|flop_OOP"][size] = "FLOP|" + node
        t["FLOP|" + node] = {"C": "TURN:" + line, "F": "END"}
    return t


def link_turn(nodes):
    """Points every turn action at the node it leads to.

    Defence nodes are named by the bet as a share of the pot - turn_IP_vs33 is
    IP facing a third-pot bet - while the action reaching one carries an
    absolute size, R2.5. The two cannot be matched by name: the same 33% is a
    different number on every board and in every line, and the turn menu is not
    the flop's fixed four sizes but anything from 10% to 200%, so there is no
    size table to read it out of the way build_tree does for the flop.

    They are matched by the pot instead. A node reached by a bet holds exactly
    the parent's pot plus that bet, which is arithmetic rather than convention
    and so needs nothing kept in step with the collector. Checked over the 40bb
    cache: of 4056 (defence node, turn card) pairs sampled, every one matched
    exactly one action of its parent, none matched two, and the share of the pot
    always agreed with the name.

    Counts are returned rather than printed so the caller can total them across
    groups. The one that means something is wrong is a collected defence node
    nothing points at - `defence` minus the links made. A turn bet with no node
    is NOT that: the collector took a subset of each turn menu deliberately
    (run_defence2.bat's header is a table of reach per request), so most of the
    menu having no data behind it is the collection working as planned, and
    reporting it as a fault buries the number that is a fault.
    """
    faced = defaultdict(list)
    for key, n in nodes.items():
        parts = key.split("|")
        if len(parts) != 3:
            continue
        line, node, card = parts
        if node.startswith("turn_IP_vs"):
            faced[(line, card, "turn_OOP")].append((n["pot"], key))
        elif node.startswith("turn_OOP_vs"):
            faced[(line, card, "turn_IP")].append((n["pot"], key))

    stats = defaultdict(int)
    stats["defence"] = sum(len(v) for v in faced.values())
    for key, n in nodes.items():
        parts = key.split("|")
        if len(parts) != 3 or not parts[1].startswith("turn_"):
            continue
        line, node, card = parts
        opening = node in ("turn_OOP", "turn_IP")
        table = faced.get((line, card, node), []) if opening else []
        # Only OOP opening the turn has a check that leads anywhere. The check
        # behind it ends the hand: no river was collected for the lines the app
        # walks, and calling or folding to a turn bet ends it for the same
        # reason.
        checked = "%s|turn_IP|%s" % (line, card) if node == "turn_OOP" else None
        taken = set()
        sizeless = []
        for a in n["actions"]:
            code = a["code"]
            if code == "X":
                a["next"] = checked if checked in nodes else "END"
            elif code in ("C", "F"):
                a["next"] = "END"
            elif a["betsize"] is None:
                sizeless.append(a)
            else:
                want = n["pot"] + a["betsize"]
                hits = [k for p, k in table
                        if abs(p - want) < 0.005 and k not in taken]
                # Two nodes at the same pot would make the choice between them
                # arbitrary, and picking one anyway is the kind of error that
                # shows up as a hand reading another hand's numbers rather than
                # as anything failing. It has never happened - counted so that
                # it cannot start happening quietly.
                if len(hits) > 1:
                    stats["ambiguous"] += 1
                if hits:
                    a["next"] = hits[0]
                    taken.add(hits[0])
                    stats["linked"] += 1
                else:
                    stats["dead_open" if opening else "dead_facing"] += 1
        # An all-in carries no size in the cache, so the pot cannot place it.
        # When it is the only bet left over and exactly one defence node is
        # also left over, the pairing is the only one available rather than a
        # guess; anything less certain than that is left unlinked.
        spare = [k for _, k in table if k not in taken]
        if len(sizeless) == 1 and len(spare) == 1:
            sizeless[0]["next"] = spare[0]
            stats["linked_allin"] += 1
        else:
            stats["dead_open" if opening else "dead_facing"] += len(sizeless)
    return stats


# Dead money already in the pot when the flop is dealt, per pair: everything
# that is not the two matched opens. Blinds and antes do not change with the
# stack, so these are the same at every depth - checked against both collected
# _sizes.json files, where every pair's pot minus twice its open lands on the
# number below.
#
# That makes the open recoverable from the pot, which is the only independent
# handle on which collection a folder holds. The 40bb _sizes.json predates the
# collector recording either the depth or the opens, so without this there is
# nothing in that folder to check a stated depth against.
DEAD_MONEY = {
    "UTG_vs_BB": 1.5, "BTN_vs_BB": 1.5, "UTG_vs_BTN": 2.5,
    "SB_vs_BB": 1.0, "UTG_vs_SB": 2.0, "BTN_vs_SB": 2.0,
}


def check_opens(sizes_by_pair, pairs):
    """Refuses when the opens about to be written disagree with the pots.

    The opens decide the preflop string the app matches a hand against, so
    getting them wrong does not produce an error - it produces a dataset the
    app can never reach, or worse, one it reaches for the wrong hands. When
    _sizes.json carries no opens the 40bb defaults are assumed, and this is
    what turns that assumption into something the data has agreed to.
    """
    bad = []
    for pair, s in sorted(sizes_by_pair.items()):
        pot, dead = s.get("pot"), DEAD_MONEY.get(pair)
        if not pot or dead is None or pair not in pairs:
            continue
        implied = (float(pot) - dead) / 2.0
        used = next((float(a[1:]) for a in pairs[pair]["preflop"].split("-")
                     if a.startswith("R")), None)
        if used is None or abs(implied - used) > 0.06:
            bad.append("%s: pot %.4g implies an open of %.2f, but %.2f is being used"
                       % (pair, float(pot), implied, used or 0))
    if bad:
        sys.exit("the opens do not match the pots in _sizes.json:\n  "
                 + "\n  ".join(bad)
                 + "\n\nThis usually means --cache and --sizes point at different "
                   "collections, or that a folder holds a different depth than "
                   "expected. Nothing has been written.")


def depth_folder(depth):
    """40.125 -> '40'. The quarter-blind ante is part of how the site quotes a
    stack, not part of how anyone refers to it."""
    return str(int(round(float(depth))))


def depth_label(depth):
    return "%dBB" % int(round(float(depth)))


def merge_manifest(out_root, entry):
    """Adds this depth to the top-level manifest, keeping the others.

    Converting is one depth per run, and the second run must not erase the
    first. Reading the existing manifest and replacing only this depth's entry
    is what makes the two runs additive; writing a fresh manifest would leave
    the previous depth's files on disk but unreachable, which looks like the
    conversion silently failed.
    """
    path = os.path.join(out_root, "index.json")
    manifest = {"version": 2, "depths": []}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                old = json.load(fh)
            if old.get("version") == 2 and isinstance(old.get("depths"), list):
                manifest["depths"] = [d for d in old["depths"] if d.get("id") != entry["id"]]
            elif "files" in old:
                # A v1 folder converted before depths existed. Its files sit
                # directly in postflop/ and are left exactly where they are;
                # the app still reads that layout.
                print("  note: an older single-depth index.json was here and has "
                      "been replaced by the multi-depth manifest.")
        except (ValueError, OSError):
            pass
    manifest["depths"].append(entry)
    # When this folder was last written. Shown in the app's offline panel, so a
    # phone still serving a copy from an older conversion says so instead of
    # looking fine - which is exactly how a stale copy went unnoticed.
    manifest["generated"] = entry.get("generated")
    # Deepest first, so the app's default is the one with the fullest data.
    manifest["depths"].sort(key=lambda d: -(d.get("depth") or 0))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, separators=(",", ":"))
    return manifest


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--cache", default=os.path.join(here, "turn_calib", "cache"))
    ap.add_argument("--sizes", default=os.path.join(here, "turn_calib", "_sizes.json"))
    # Defaults to a folder beside this script, so the whole app - index.html,
    # run_app.bat and the data it fetches - can live in one directory and the
    # served origin covers all of it.
    ap.add_argument("--out", default=os.path.join(here, "postflop"))
    ap.add_argument("--combos", action="store_true",
                    help="accepted for compatibility; per-combo data is always stored now")
    ap.add_argument("--limit", type=int, default=0, help="only convert N (pair,flop) groups")
    # Each depth gets its own subfolder and its own entry in the top-level
    # manifest. Derived from the depth the collector stamped into _sizes.json
    # rather than asked for, because the two must not disagree: a 20bb dataset
    # filed under "40" would be served to a hand played at 40bb, and every
    # number in it would be wrong without anything looking broken.
    ap.add_argument("--depth", type=float, default=None,
                    help="stack depth, when the folder does not record it "
                         "(the 40bb collection ran before it was recorded)")
    ap.add_argument("--depth-id", default=None,
                    help="subfolder name (default: derived from the depth)")
    ap.add_argument("--label", default=None,
                    help="how the depth is named in the app (default: '40BB')")
    args = ap.parse_args()

    if not os.path.isdir(args.cache):
        sys.exit("no cache directory at %s" % args.cache)
    with open(args.sizes, encoding="utf-8") as f:
        sizes_doc = json.load(f)
    sizes_by_pair = sizes_doc["resolved"]
    pairs = pairs_with_opens(sizes_doc.get("opens"))
    depth = sizes_doc.get("depth")
    if depth:
        print("depth %s, opens: %s" % (
            depth, ", ".join("%s %s" % (k, v["preflop"].split("-")[
                next(i for i, a in enumerate(v["preflop"].split("-")) if a.startswith("R"))])
                for k, v in sorted(pairs.items()))))

    if depth is None and args.depth is not None:
        # Stated on the command line. Not trusted on its own: check_opens below
        # holds it against the pots, so a folder that is not the depth it was
        # said to be stops here rather than being filed under the wrong name.
        depth = args.depth
    if depth is None:
        # The 40bb collection ran before the collector stamped the depth into
        # _sizes.json, so that file has only `resolved` and `menus`. _depth.json
        # sits next to it and has carried the depth since the start, so the
        # older folder converts with no extra arguments - which matters, because
        # the alternative is the user supplying a number by hand and the whole
        # dataset being mislabelled if they mistype it.
        side = os.path.join(os.path.dirname(os.path.abspath(args.sizes)), "_depth.json")
        if os.path.exists(side):
            try:
                with open(side, encoding="utf-8") as fh:
                    depth = json.load(fh).get("depth")
                if depth:
                    print("depth %s (from _depth.json; _sizes.json predates the field)" % depth)
            except (ValueError, OSError):
                pass
    if depth is None and not args.depth_id:
        sys.exit("neither _sizes.json nor _depth.json says what stack depth this "
                 "cache is, and --depth-id was not given; refusing to guess")
    check_opens(sizes_by_pair, pairs)
    depth_id = args.depth_id or depth_folder(depth)
    label = args.label or depth_label(depth)
    out_dir = os.path.join(args.out, depth_id)
    print("writing depth '%s' (%s) to %s" % (depth_id, label, out_dir))

    files = [f for f in sorted(os.listdir(args.cache)) if f.endswith(".jsonl")]
    by_flop = defaultdict(list)
    for fn in files:
        pair, flop, line, node = fn[:-6].split("__")
        by_flop[(pair, flop)].append((line, node, os.path.join(args.cache, fn)))

    os.makedirs(out_dir, exist_ok=True)
    index = {
        "pairs": {k: {"preflop": v["preflop"], "oop": v["oop"], "ip": v["ip"]} for k, v in pairs.items()},
        "depth": depth,
        "sizes": sizes_by_pair,
        "handOrder": HAND_ORDER,
        "combos": True,
        "files": {},
    }

    keys = sorted(by_flop)
    if args.limit:
        keys = keys[:args.limit]
    total_bytes = 0
    link_totals = defaultdict(int)
    missing_sizes = sorted({p for p, _ in keys} - set(sizes_by_pair))
    if missing_sizes:
        # A pair the crawler skipped (unverified bet sizes) has no entry in
        # _sizes.json, so its action tree cannot be built. Say so instead of
        # dying on a KeyError partway through a 25-minute run.
        print("skipping %s: no resolved bet sizes in _sizes.json" % ", ".join(missing_sizes))
        keys = [k for k in keys if k[0] in sizes_by_pair]
    for i, (pair, flop) in enumerate(keys):
        tree = build_tree(sizes_by_pair[pair])
        nodes = {}
        for line, node, path in by_flop[(pair, flop)]:
            with open(path, encoding="utf-8") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        rec = json.loads(raw)
                    except ValueError:
                        continue
                    if not rec.get("strategy") or not rec.get("evs") or not rec.get("reach"):
                        continue
                    card = rec["card"]
                    key = "%s|%s" % (line, node) if card == "-" else "%s|%s|%s" % (line, node, card)
                    pot = float(rec.get("pot") or 0)
                    metas = [action_meta(c, pot) for c in rec["actions"]]
                    # Flop successors come straight from the plan. Turn ones are
                    # filled in by link_turn after the whole group is read: a
                    # bet is placed by the pot it makes, and the node holding
                    # that pot is usually in a file not opened yet.
                    succ = tree.get(key, {}) if line == "FLOP" else {}
                    packed = aggregate(rec)
                    nodes[key] = {
                        "side": "oop" if "OOP" in node else "ip",
                        "pot": pot,
                        "actions": [
                            {**m, "next": succ.get(m["code"])} for m in metas
                        ],
                        **packed,
                    }
        if not nodes:
            continue
        for k, v in link_turn(nodes).items():
            link_totals[k] += v
        blob = gzip.compress(json.dumps({
            "pair": pair, "flop": flop, "nodes": nodes,
        }, separators=(",", ":")).encode("utf-8"), 9)
        out_name = "%s__%s.json.gz" % (pair, flop)
        with open(os.path.join(out_dir, out_name), "wb") as fh:
            fh.write(blob)
        total_bytes += len(blob)
        index["files"].setdefault(pair, {})[flop] = {"file": out_name, "nodes": len(nodes)}
        if (i + 1) % 20 == 0 or i + 1 == len(keys):
            print("  %d/%d groups, %.1f MB so far" % (i + 1, len(keys), total_bytes / 1048576))

    with open(os.path.join(out_dir, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh, separators=(",", ":"))

    n_flops = sum(len(v) for v in index["files"].values())
    manifest = merge_manifest(args.out, {
        "id": depth_id, "label": label, "depth": depth,
        "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "index": "%s/index.json" % depth_id,
        "pairs": len(index["files"]), "flops": n_flops,
        "bytes": total_bytes,
    })
    print("\nwrote %d files for %d pairs / %d (pair,flop) groups" % (n_flops + 1, len(index["files"]), n_flops))
    print("total %.1f MB (%.2f MB average per flop file)"
          % (total_bytes / 1048576, total_bytes / max(1, n_flops) / 1048576))
    print("resolution: per combo (1326) - the app aggregates to 169 itself")
    # Two separate facts, kept apart. The first is about this script: every
    # collected node has to be reachable or it was converted for nothing. The
    # second is about the collection: a turn menu offers more sizes than were
    # ever asked for, and the ones that were skipped read as "no data" in the
    # app, which is correct rather than broken.
    reached = link_totals["linked"] + link_totals["linked_allin"]
    orphaned = link_totals["defence"] - reached
    bets = reached + link_totals["dead_open"]
    print("turn defence: %d of %d collected nodes are reachable"
          % (reached, link_totals["defence"]))
    print("  %d of %d turn bets lead to one (%.0f%%); the rest were never collected"
          % (reached, bets, reached * 100.0 / max(1, bets)))
    if link_totals["linked_allin"]:
        print("  %d all-in placed by elimination" % link_totals["linked_allin"])
    print("  %d raises over a turn bet have no node (none were collected)"
          % link_totals["dead_facing"])
    if orphaned:
        # Collected, converted, shipped to the phone, and unreachable. Either
        # the pot arithmetic link_turn relies on has stopped holding, or a
        # defence node was collected whose parent was not.
        print("  WARNING: %d collected defence nodes are not reachable from any bet"
              % orphaned)
    if link_totals["ambiguous"]:
        print("  WARNING: %d turn bets matched more than one defence node by pot;"
              " the first was used" % link_totals["ambiguous"])
    print("\ndepths now in %s:" % args.out)
    for d in manifest["depths"]:
        print("  %-4s %-6s %d pairs / %d flops / %.0f MB"
              % (d["id"], d["label"], d["pairs"], d["flops"], d["bytes"] / 1048576))


if __name__ == "__main__":
    main()
