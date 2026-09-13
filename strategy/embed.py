"""Puts the built tables inside drill.html.

The app is one file so it can be opened from a phone with no server, which
means the tables travel inside it. Each depth gets its own script tag, tagged
with the stack it is for; the app reads every tag it finds, so adding 80BB
later is one more argument here and no change to the app.

    python strategy/embed.py 40BB_SRP.json 20BB_SRP.json

The JSONs to name are the ones built with --alloc: those are the rules that
are meant to be memorised, and the drill should not ask for lines that were
deliberately left out of the memorisation budget.
"""
import json
import re
import sys

APP = 'drill.html'
TAG = re.compile(r'<script type="application/json"[^>]*>.*?</script>\n?', re.S)


def block(path):
    d = json.load(open(path, encoding='utf-8'))
    depth = d.get('depth')
    if not depth:
        sys.exit("%s carries no 'depth' - rebuild it with a build.py that "
                 "writes one, or the app cannot label the question." % path)
    # separators without spaces: the file is downloaded to a phone
    body = json.dumps(d, ensure_ascii=False, separators=(',', ':'))
    if '</script' in body:
        sys.exit('%s contains a closing script tag and would break the page' % path)
    return ('<script type="application/json" data-depth="%s" id="data-%s">%s</script>\n'
            % (depth, depth, body))


def main(paths):
    html = open(APP, encoding='utf-8').read()
    found = TAG.findall(html)
    if not found:
        sys.exit('no data script tag in %s - has the app changed shape?' % APP)

    blocks = ''.join(block(p) for p in paths)
    # Replace the first tag with all of them and drop the rest, so running
    # this twice does not leave a depth behind that is no longer named.
    html = TAG.sub(lambda m: blocks if m.group(0) == found[0] else '', html, count=len(found))
    open(APP, 'w', encoding='utf-8').write(html)

    for p in paths:
        d = json.load(open(p, encoding='utf-8'))
        print('%-18s %-6s %2d spots, %3d rules'
              % (p, d['depth'], len(d['spots']),
                 sum(len(s['rules']) for s in d['spots'])))
    print('%s: %d bytes' % (APP, len(html.encode('utf-8'))))


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
