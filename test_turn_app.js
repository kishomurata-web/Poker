/* Checks that what postflop_convert.py writes is what index.html can walk.
 *
 * The two halves of the turn-defence fix were written against each other but
 * never actually joined: the converter's tests assert on the JSON it produces,
 * and the app's tests never see a converted file. That gap is exactly where
 * the original bug lived for months - the nodes were in the file, the app was
 * willing to show them, and nothing pointed from one to the other.
 *
 * So this runs the real converter over a small cache, then hands the file it
 * wrote to the real page and walks it with the app's own functions.
 *
 *   node test_turn_app.js
 */

const { execFileSync } = require('child_process');
const http = require('http');
const fs = require('fs');
const os = require('os');
const path = require('path');
const zlib = require('zlib');
const { chromium } = require('playwright');

const ROOT = __dirname;
let passed = 0;
const failures = [];

function ok(name, cond, extra) {
  if (cond) { passed++; console.log('  PASS  ' + name); return; }
  failures.push(name);
  console.log('  FAIL  ' + name + (extra ? '\n          ' + extra : ''));
}

/* The same cache test_convert.py builds, converted by the same converter. Going
   through the file on disk rather than rebuilding the JSON here is the point:
   a key the converter spells differently from the app is the failure this is
   looking for, and a hand-written fixture would spell it the way the test
   author expected instead. */
function convert() {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'turnapp'));
  execFileSync('python3', ['-c', `
import sys, os, json
sys.path.insert(0, ${JSON.stringify(ROOT)})
import test_convert as tc
tmp = ${JSON.stringify(tmp)}
cache = os.path.join(tmp, 'cache')
tc.build_cache(cache)
with open(os.path.join(tmp, '_sizes.json'), 'w') as fh:
    json.dump({"depth": 40.125,
               "resolved": {tc.PAIR: {"pot": tc.FLOP_POT, "c33": "R2"}}}, fh)
`], { stdio: 'pipe' });
  execFileSync('python3', [path.join(ROOT, 'postflop_convert.py'),
    '--cache', path.join(tmp, 'cache'), '--sizes', path.join(tmp, '_sizes.json'),
    '--out', path.join(tmp, 'out')], { stdio: 'pipe' });
  const file = path.join(tmp, 'out', '40', 'BTN_vs_BB__3h3d2s.json.gz');
  return JSON.parse(zlib.gunzipSync(fs.readFileSync(file)).toString('utf8'));
}

const TYPES = { '.html': 'text/html', '.js': 'text/javascript',
                '.json': 'application/json', '.webmanifest': 'application/manifest+json' };

(async () => {
  const data = convert();

  const srv = http.createServer((req, res) => {
    const url = req.url.split('?')[0];
    if (url === '/postflop/index.json') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      return res.end('{"version":2,"depths":[]}');
    }
    const p = path.join(ROOT, url === '/' ? 'index.html' : url.replace(/^\//, ''));
    if (!p.startsWith(ROOT) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) {
      res.writeHead(404); return res.end('no');
    }
    res.writeHead(200, { 'Content-Type': TYPES[path.extname(p)] || 'application/octet-stream' });
    res.end(fs.readFileSync(p));
  });
  await new Promise((r) => srv.listen(0, r));

  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(`http://127.0.0.1:${srv.address().port}/index.html`, { waitUntil: 'load' });
  await page.waitForFunction(
    'typeof pfResolveNext === "function" && typeof pfNodeName === "function"',
    null, { timeout: 15000 });

  const walk = await page.evaluate((data) => {
    const at = (key, code) => {
      const node = data.nodes[key];
      if (!node) return { missing: key };
      const act = node.actions.find((a) => a.code === code);
      if (!act) return { noAction: code, had: node.actions.map((a) => a.code) };
      return { to: pfResolveNext(data, act.next) };
    };
    return {
      // OOP opens the turn for a fifth of the pot. The app has to land on the
      // node for IP facing exactly that bet, not on some other size.
      bet20: at('XC33|turn_OOP|Kc', 'R2.02'),
      bet50: at('XC33|turn_OOP|Kc', 'R5.05'),
      check: at('XC33|turn_OOP|Kc', 'X'),
      ipBet: at('XC33|turn_IP|Kc', 'R3.333'),
      // Facing the bet: calling and folding both end the hand, and a raise has
      // nowhere to go because no raise node was ever collected.
      call: at('XC33|turn_IP_vs20|Kc', 'C'),
      fold: at('XC33|turn_IP_vs20|Kc', 'F'),
      raise: at('XC33|turn_IP_vs20|Kc', 'R6'),
      // A size the collector skipped. The app must keep saying so.
      uncollected: at('XC75|turn_OOP|7d', 'R3.0'),
      sides: {
        ipFacing: (data.nodes['XC33|turn_IP_vs20|Kc'] || {}).side,
        oopFacing: (data.nodes['XC33|turn_OOP_vs33|Kc'] || {}).side,
      },
      labels: {
        ip20: pfNodeName('turn_IP_vs20'),
        oop33: pfNodeName('turn_OOP_vs33'),
        ip125: pfNodeName('turn_IP_vs125'),
        opening: pfNodeName('turn_OOP'),
      },
    };
  }, data);

  console.log('\nthe app resolves what the converter wrote');
  ok("OOP's 20% lands on IP facing 20%",
    walk.bet20.to === 'XC33|turn_IP_vs20|Kc', JSON.stringify(walk.bet20));
  ok("OOP's 50% lands on IP facing 50%",
    walk.bet50.to === 'XC33|turn_IP_vs50|Kc', JSON.stringify(walk.bet50));
  ok('a check still reaches IP',
    walk.check.to === 'XC33|turn_IP|Kc', JSON.stringify(walk.check));
  ok("IP's bet lands on OOP facing it",
    walk.ipBet.to === 'XC33|turn_OOP_vs33|Kc', JSON.stringify(walk.ipBet));

  console.log('\nand keeps the ends of the tree honest');
  ok('calling a turn bet ends the hand', walk.call.to === 'END', JSON.stringify(walk.call));
  ok('folding to it ends the hand', walk.fold.to === 'END', JSON.stringify(walk.fold));
  ok('a raise over it reports no data', walk.raise.to === null, JSON.stringify(walk.raise));
  ok('a bet size that was never collected reports no data',
    walk.uncollected.to === null, JSON.stringify(walk.uncollected));

  console.log('\nthe defence nodes are attributed to the right player');
  ok('IP is the one facing OOP\'s bet', walk.sides.ipFacing === 'ip', walk.sides.ipFacing);
  ok('OOP is the one facing IP\'s bet', walk.sides.oopFacing === 'oop', walk.sides.oopFacing);

  console.log('\nand the app has a name for every one of them');
  ok('IP facing 20%', walk.labels.ip20 === 'ターン IP（OOPの20%ベットに直面）', walk.labels.ip20);
  ok('OOP facing 33%', walk.labels.oop33 === 'ターン OOP（IPの33%ベットに直面）', walk.labels.oop33);
  // Over-pot sizes are on the turn menu and are not on the flop's, so a label
  // scheme built from the flop's four sizes would fall through to a raw key.
  ok('IP facing an over-pot bet',
    walk.labels.ip125 === 'ターン IP（OOPの125%ベットに直面）', walk.labels.ip125);
  ok('and the opening nodes keep the names they had',
    walk.labels.opening === 'ターン OOP 先手', walk.labels.opening);

  ok('nothing threw along the way', errors.length === 0, errors.join(' | '));

  await browser.close();
  srv.close();
  console.log(`\n=== ${passed} passed, ${failures.length} failed ===`);
  process.exit(failures.length ? 1 : 0);
})();
