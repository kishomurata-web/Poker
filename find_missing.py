"""Looks for the eight turn groups the 40BB export came back short on.

    python find_missing.py

Three independent questions, because "the export dropped them" and "they were
never collected" need different answers and only one of them can be fixed
without the site:

  1. Is the file there under the name the exporter expects?
  2. Is it there under some other spelling, or in some other folder?
  3. Does anything on disk say what happened when it should have been fetched?

The board spellings below are the cache's own - export_freqs.py reads them
straight out of the filename and does not relabel - so they are what the files
would be called if they existed.
"""
import collections
import glob
import io
import os
import re
import sys

CACHE = os.path.join('turn_calib', 'cache')
LINE, NODE = 'XC75', 'turn_IP'
MISSING = [
    ('BTN_vs_BB', '7s7h6s'), ('BTN_vs_BB', 'As6s6h'), ('BTN_vs_BB', 'JsJh9s'),
    ('BTN_vs_BB', 'KsKh7s'), ('BTN_vs_BB', 'KsTsTh'),
    ('BTN_vs_SB', '6s4s3s'),
    ('SB_vs_BB', '6s4s3s'), ('SB_vs_BB', 'AsAh7s'),
]
NAME = '%s__%s__%s__%s.jsonl'


def out(s=''):
    print(s)


def q1_named_cache():
    out('1. Under %s, by the exact name' % CACHE)
    if not os.path.isdir(CACHE):
        out('   no such folder - run this from the folder holding turn_calib\\')
        return
    for pair, board in MISSING:
        p = os.path.join(CACHE, NAME % (pair, board, LINE, NODE))
        if os.path.exists(p):
            n = sum(1 for _ in open(p, encoding='utf-8') if _.strip())
            out('   PRESENT  %-34s %d lines, %d bytes'
                % (os.path.basename(p), n, os.path.getsize(p)))
        else:
            out('   absent   %s' % os.path.basename(p))


def q1b_sibling():
    """The same board at turn_OOP. If that is there and healthy, the board was
    reached and the crawl simply did not come back with the IP half."""
    out()
    out('   the turn_OOP sibling of each, for comparison')
    for pair, board in MISSING:
        p = os.path.join(CACHE, NAME % (pair, board, LINE, 'turn_OOP'))
        if os.path.exists(p):
            n = sum(1 for _ in open(p, encoding='utf-8') if _.strip())
            out('   PRESENT  %-34s %d lines' % (os.path.basename(p), n))
        else:
            out('   absent   %s' % os.path.basename(p))


def q2_other_spelling():
    """Which boards this (pair, line, node) does hold, against which the same
    pair and line hold at turn_OOP. A board in the second list and not the
    first is missing; a board in neither was never part of the job."""
    out()
    out('2a. Board spellings held, IP against OOP')
    for pair in sorted({p for p, _ in MISSING}):
        def boards(node):
            pat = os.path.join(CACHE, '%s__*__%s__%s.jsonl' % (pair, LINE, node))
            return {os.path.basename(x).split('__')[1] for x in glob.glob(pat)}
        ip, oop = boards(NODE), boards('turn_OOP')
        out('   %-12s IP %d, OOP %d' % (pair, len(ip), len(oop)))
        only_oop = sorted(oop - ip)
        only_ip = sorted(ip - oop)
        if only_oop:
            out('      OOP only (missing at IP): %s' % ' '.join(only_oop))
        if only_ip:
            out('      IP only: %s' % ' '.join(only_ip))
        if not only_oop and not only_ip:
            out('      the two sets match')


def q2b_anywhere(root='.'):
    """The same filenames anywhere below here, in case another run wrote them
    into a different folder."""
    out()
    out('2b. The same names anywhere below %s' % os.path.abspath(root))
    want = {NAME % (p, b, LINE, NODE) for p, b in MISSING}
    hits = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(('.', '__', 'node_modules'))]
        for f in filenames:
            if f in want:
                out('   found  %s' % os.path.join(dirpath, f))
                hits += 1
    if not hits:
        out('   none')

    out()
    out('   every folder holding XC75 turn_IP files, and how many')
    per = collections.Counter()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(('.', '__', 'node_modules'))]
        n = sum(1 for f in filenames if f.endswith('__%s__%s.jsonl' % (LINE, NODE)))
        if n:
            per[os.path.relpath(dirpath, root)] = n
    if per:
        for d, n in per.most_common():
            out('   %-56s %5d' % (d, n))
    else:
        out('   none')


def q3_logs(root='.'):
    """Anything written down about these boards - a run that gave up leaves a
    line behind, and that says whether it was tried at all."""
    out()
    out('3. Log files mentioning those boards or that line')
    boards = {b for _, b in MISSING}
    pat = re.compile('|'.join([re.escape(b) for b in boards] + [r'XC75']))
    looked = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(('.', '__', 'node_modules'))]
        for f in filenames:
            if not (f.endswith(('.txt', '.log')) or f.startswith('_')):
                continue
            p = os.path.join(dirpath, f)
            try:
                if os.path.getsize(p) > 40 * 1024 * 1024:
                    continue
                with io.open(p, encoding='utf-8', errors='replace') as fh:
                    looked += 1
                    for i, line in enumerate(fh, 1):
                        if pat.search(line):
                            out('   %s:%d  %s' % (os.path.relpath(p, root), i,
                                                  line.strip()[:150]))
            except OSError:
                pass
    out('   (%d log-ish files read)' % looked)


if __name__ == '__main__':
    root = sys.argv[1] if len(sys.argv) > 1 else '.'
    os.chdir(root)
    out('looking from %s' % os.path.abspath('.'))
    out()
    q1_named_cache()
    q1b_sibling()
    q2_other_spelling()
    q2b_anywhere()
    q3_logs()
