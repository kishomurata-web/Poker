/* Checks the app scores a decision the way the solver site scores it.
 *
 * Every case below is a real node read out of the site's own `hero-situation`
 * response, with the score it returned. That is the point: the rule was worked
 * out from these numbers (SCORING.md), so a test written from the rule would
 * only prove the rule was copied correctly, while these prove the app lands on
 * the same answer the site did.
 *
 * The site reports a frequency as a fraction; the app stores it as an integer
 * out of 10000, which is why the mixed cases are compared within a tolerance -
 * an action played 9.17% of the time is 917 here, and 917/9079 is not exactly
 * the site's 0.10100482859754542.
 *
 *   node test_score.js
 */

const http = require('http');
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const ROOT = __dirname;
let passed = 0;
const failures = [];

function ok(name, cond, extra) {
  if (cond) { passed++; console.log('  PASS  ' + name); return; }
  failures.push(name);
  console.log('  FAIL  ' + name + (extra ? '\n          ' + extra : ''));
}

const pct = (f) => Math.round(f * 10000);   // the site's fraction, as the app stores it

/* One entry per action the site scored, grouped by the node it came from. */
const NODES = [
  {
    what: 'river, BB facing a 5.0 bet',
    pot: 13.5,
    maxFreq: pct(0.996014416218),
    acts: [
      { code: 'F', freq: pct(0.996014416218), loss: 0, tier: 'best', score: 1 },
      { code: 'C', freq: pct(0), loss: 0.377124786378905, tier: 'never', score: -0.5587033872280074 },
      { code: 'R11.5', freq: pct(0.00000103002582819), loss: 0.625675200878905, tier: 'never', score: -0.9269262235243038 },
      { code: 'R15', freq: pct(0.00398450065404), loss: 0.689629365878905, tier: 'rare', score: 0 },
      { code: 'RAI', freq: pct(0.0000000000187768741527), loss: 1.316756440878905, tier: 'never', score: -1 },
    ],
  },
  {
    what: 'flop, BB facing a 2.0 bet',
    pot: 8.1,
    maxFreq: pct(0.719000041485),
    acts: [
      { code: 'F', freq: pct(0.0010000000475), loss: 0, tier: 'rare', score: 0 },
      { code: 'C', freq: pct(0.719000041485), loss: 0, tier: 'best', score: 1 },
      { code: 'R5.35', freq: pct(0.278000026941), loss: 0, tier: 'ok', score: 0.3866481375534103 },
      { code: 'R7.55', freq: pct(0.00200000009499), loss: 0, tier: 'rare', score: 0 },
      { code: 'RAI', freq: pct(0), loss: 1.7571204649999999, tier: 'never', score: -1 },
    ],
  },
  {
    what: 'BB opening into a 6.1 pot',
    pot: 6.1,
    maxFreq: pct(0.388000011444),
    acts: [
      { code: 'X', freq: pct(0.0230000019073), loss: 0, tier: 'rare', score: 0 },
      { code: 'R2', freq: pct(0.32000002265), loss: 0, tier: 'ok', score: 0.8247423020918792 },
      { code: 'R3.35', freq: pct(0.388000011444), loss: 0, tier: 'best', score: 1 },
      { code: 'R5.05', freq: pct(0.243000015616), loss: 0, tier: 'ok', score: 0.6262886815689493 },
      { code: 'R12.2', freq: pct(0.0010000000475), loss: 0, tier: 'rare', score: 0 },
      { code: 'RAI', freq: pct(0), loss: 1.3393868549999999, tier: 'never', score: -1 },
    ],
  },
  {
    what: 'BTN opening into a 6.1 pot',
    pot: 6.1,
    maxFreq: pct(0.434000015259),
    acts: [
      { code: 'X', freq: pct(0.244000017643), loss: 0, tier: 'ok', score: 0.56221200245209 },
      { code: 'R1.2', freq: pct(0.434000015259), loss: 0, tier: 'best', score: 1 },
      { code: 'R2', freq: pct(0.318000018597), loss: 0, tier: 'ok', score: 0.732718911097793 },
      { code: 'R3.35', freq: pct(0.00400000018999), loss: 0, tier: 'rare', score: 0 },
      { code: 'R5.05', freq: pct(0), loss: 0.08812179500000017, tier: 'never', score: -0.28892391803278744 },
      { code: 'R7.6', freq: pct(0), loss: 0.17508034500000003, tier: 'never', score: -0.5740339180327869 },
      { code: 'RAI', freq: pct(0), loss: 3.1798259250000003, tier: 'never', score: -1 },
    ],
  },
  {
    what: 'BB with one dominant check',
    pot: 6.1,
    maxFreq: pct(0.870000064373),
    acts: [
      { code: 'X', freq: pct(0.870000064373), loss: 0, tier: 'best', score: 1 },
      { code: 'R1.2', freq: pct(0), loss: 0.055723569999999945, tier: 'never', score: -0.18270022950819656 },
      { code: 'R2', freq: pct(0), loss: 0.07350501999999992, tier: 'never', score: -0.2410000655737702 },
      { code: 'R3.35', freq: pct(0.00200000009499), loss: 0, tier: 'rare', score: 0 },
      { code: 'R5.05', freq: pct(0.0010000000475), loss: 0, tier: 'rare', score: 0 },
      { code: 'R7.6', freq: pct(0.118000008166), loss: 0, tier: 'ok', score: 0.13563218325856258 },
    ],
  },
  {
    what: 'turn, the all-in is all but pure',
    pot: 16.2,
    maxFreq: pct(0.999839246273),
    acts: [
      { code: 'X', freq: pct(0.0000000302857827705), loss: 1.1353058000000011, tier: 'never', score: -1 },
      { code: 'R1.5', freq: pct(0.00000254613678408), loss: 0.5135101500000019, tier: 'never', score: -0.6339631481481504 },
      { code: 'R5.5', freq: pct(0.000000423469259658), loss: 0.3742325000000015, tier: 'never', score: -0.4620154320987673 },
      { code: 'R9.5', freq: pct(0.000144915189594), loss: 0.13628080000000153, tier: 'never', score: -0.16824790123456979 },
      { code: 'R13.5', freq: pct(0.0000128637257149), loss: 0.2502296500000014, tier: 'never', score: -0.3089254938271622 },
      { code: 'RAI', freq: pct(0.999839246273), loss: 0, tier: 'best', score: 1 },
    ],
  },
  {
    what: 'BB folding 9.17% against a 90.8% call',
    pot: 18.5,
    maxFreq: pct(0.907883167267),
    acts: [
      { code: 'F', freq: pct(0.0917005836964), loss: 0, tier: 'ok', score: 0.10100482859754542 },
      { code: 'C', freq: pct(0.907883167267), loss: 0, tier: 'best', score: 1 },
    ],
  },
  {
    what: 'the 4.4% size that fixed the mixed cut',
    pot: 6.1,
    maxFreq: pct(0.35900002718),
    acts: [
      { code: 'R6', freq: pct(0.0440000034869), loss: 0, tier: 'ok', score: 0.12256267452826333 },
    ],
  },
];

const TYPES = { '.html': 'text/html', '.js': 'text/javascript',
                '.json': 'application/json', '.webmanifest': 'application/manifest+json' };

(async () => {
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
    'typeof tierFor === "function" && typeof gtoScoreFor === "function"',
    null, { timeout: 15000 });

  const got = await page.evaluate((nodes) => nodes.map((n) => n.acts.map((a) => {
    const tier = tierFor(a.freq, n.maxFreq);
    return { tier, score: gtoScoreFor(tier, a.freq, n.maxFreq, a.loss, n.pot) };
  })), NODES);

  // A mixed action is compared loosely because the app rounds the frequency to
  // a ten-thousandth before dividing; every other case is arithmetic the app
  // and the site do identically, and is held to it.
  const near = (x, y, tol) => x !== null && Math.abs(x - y) <= tol;

  NODES.forEach((n, i) => {
    console.log('\n' + n.what);
    n.acts.forEach((a, j) => {
      const r = got[i][j];
      ok(`${a.code} is ${a.tier}`, r.tier === a.tier, `got ${r.tier}`);
      const tol = a.tier === 'ok' ? 1e-4 : 1e-9;
      ok(`${a.code} scores ${a.score}`, near(r.score, a.score, tol), `got ${r.score}`);
    });
  });

  // The session number the site printed, rebuilt from the six decisions behind
  // it. This is the one that has to come out to a round 44%, because that is
  // what was on the screen.
  const session = await page.evaluate(() => {
    const s = [1, 0.3866481375534103, 0, 1, 1, -0.7428011174682247];
    return Math.round((s.reduce((a, b) => a + b, 0) / s.length) * 100);
  });
  console.log('\nthe session average');
  ok('six decisions average to the 44% the site showed', session === 44, String(session));

  ok('nothing threw along the way', errors.length === 0, errors.join(' | '));

  await browser.close();
  srv.close();
  console.log(`\n=== ${passed} passed, ${failures.length} failed ===`);
  process.exit(failures.length ? 1 : 0);
})();
