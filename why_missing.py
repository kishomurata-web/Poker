"""Asks _dead.jsonl what happened to the eight groups the 40BB turn is short.

    python why_missing.py

The collector writes a line there for every card it asked for and did not get,
with the reason. So this separates the two cases that matter:

  never asked      the crawl did not reach the group - re-running it collects
  asked, refused   the site has nothing there, and re-running changes nothing

Writes why_missing.txt. The file is small; the console gets the whole summary.
"""
import collections
import io
import json
import os
import sys

DEAD = os.path.join('turn_calib', '_dead.jsonl')
LINE = 'XC75'
GROUPS = [
    ('BTN_vs_BB', '7s7h6s'), ('BTN_vs_BB', 'As6s6h'), ('BTN_vs_BB', 'JsJh9s'),
    ('BTN_vs_BB', 'KsKh7s'), ('BTN_vs_BB', 'KsTsTh'),
    ('BTN_vs_SB', '6s4s3s'),
    ('SB_vs_BB', '6s4s3s'), ('SB_vs_BB', 'AsAh7s'),
]
OUT = 'why_missing.txt'

REP = []


def say(s=''):
    print(s)
    REP.append(s)


def main(root='.'):
    os.chdir(root)
    if not os.path.exists(DEAD):
        say('no %s - nothing recorded about failed fetches' % DEAD)
        return

    # key is "<pair>__<board>__<line>__<node>"; count cards per (group, node, why)
    per = collections.defaultdict(collections.Counter)
    nodes_seen = collections.defaultdict(set)
    total = 0
    with io.open(DEAD, encoding='utf-8', errors='replace') as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            total += 1
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            key = rec.get('key') or ''
            parts = key.split('__')
            if len(parts) < 4:
                continue
            pair, board, line, node = parts[0], parts[1], parts[2], '__'.join(parts[3:])
            if line != LINE or (pair, board) not in GROUPS:
                continue
            per[(pair, board)][(node, (rec.get('why') or '').strip())] += 1
            nodes_seen[(pair, board)].add(node)

    say('%s holds %d records' % (DEAD, total))
    say()
    for g in GROUPS:
        say('%s  %s' % g)
        if g not in per:
            say('   nothing recorded - the crawl never asked for this group')
            say()
            continue
        body = [x for x in per[g] if x[0] == 'turn_IP']
        if body:
            for node, why in sorted(body):
                say('   turn_IP itself:  %-46s %d cards' % (why, per[g][(node, why)]))
        else:
            say('   turn_IP itself:  no record - never asked, or asked and got data')
        others = sorted(x for x in per[g] if x[0] != 'turn_IP')
        for node, why in others[:12]:
            say('   %-22s %-46s %d cards' % (node, why, per[g][(node, why)]))
        if len(others) > 12:
            say('   ... and %d more node/reason pairs' % (len(others) - 12))
        say()

    say('reasons across these groups, all nodes')
    tally = collections.Counter()
    for g, c in per.items():
        for (node, why), n in c.items():
            tally[why] += n
    for why, n in tally.most_common():
        say('   %-50s %d cards' % (why or '(blank)', n))

    with io.open(OUT, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(REP) + '\n')
    print()
    print('written to %s' % os.path.abspath(OUT))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '.')
