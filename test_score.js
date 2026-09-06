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
  // it - and rebuilt the way the app builds it, one rounded percent at a time,
  // because that is the arithmetic that has to land on the same 44%.
  const session = await page.evaluate(() => {
    state.stats.evSum = 0;
    state.stats.evCount = 0;
    [1, 0.3866481375534103, 0, 1, 1, -0.7428011174682247].forEach(countScore);
    return { sum: state.stats.evSum, n: state.stats.evCount,
             avg: Math.round(state.stats.evSum / state.stats.evCount) };
  });
  console.log('\nthe session average');
  ok('every decision is counted', session.n === 6, String(session.n));
  ok('six decisions average to the 44% the site showed',
    session.avg === 44, `${session.sum}/${session.n} = ${session.avg}`);

  // The popup is where both numbers are read, so the wiring is checked here
  // rather than left to be noticed on a phone.
  const popup = await page.evaluate(() => {
    const txt = (id) => document.getElementById(id).textContent;
    const shown = (id) => document.getElementById(id).style.display !== 'none';
    const out = {};
    renderDecisionScore(0.5622120024, 0.34, 'var(--ok)', 'bb');
    out.score = txt('popup-score');
    out.loss = txt('popup-ev');
    out.scoreShown = shown('popup-score');
    renderDecisionScore(-0.7428011174682247, 2.4289, 'var(--never)', 'bb');
    out.negative = txt('popup-score');
    renderDecisionScore(1, null, 'var(--best)', 'bb');
    out.lossRowHidden = !shown('popup-ev-row');
    renderDecisionScore(null, null, 'var(--best)', 'bb');
    out.noScoreHidden = !shown('popup-score');

    Object.assign(state.stats, { best: 3, ok: 1, rare: 1, never: 1 });

    /* A session sitting at 44% and a hand that just went badly. The popup has
       to report the hand - the session average is what stops moving, and
       "how did that one go" is the only question being asked here. */
    state.handScores = [0, -74, 0, 100, 0, 0];
    HAND_SCORES.length = 0;
    for (let i = 0; i < 25; i++) HAND_SCORES.push(i < 5 ? 100 : 40);
    out.opened = showSessionPopup(Math.round(mean(state.handScores)));
    out.hand = txt('session-score');
    out.counts = txt('session-count');
    out.sessionAvg = Math.round(state.stats.evSum / state.stats.evCount);
    out.only = ['tier-view', 'grid-view', 'session-view']
      .filter((v) => document.getElementById(v).style.display !== 'none');
    out.overlay = document.getElementById('overlay').classList.contains('show');
    document.getElementById('overlay').classList.remove('show');

    out.recent = recentHandsAverage();
    updateStatsUI();
    out.corner = document.getElementById('tb-recent').textContent;

    // banking a hand keeps only the last of many, and never an empty one
    state.handScores = [80, 60];
    out.banked = recordHandScore();
    out.afterBank = recentHandsAverage();
    state.handScores = [];
    out.emptyBank = recordHandScore();

    out.silent = showSessionPopup(null);
    return out;
  });

  console.log('\nthe popup');
  ok('the score is the headline', popup.score === '56%' && popup.scoreShown, popup.score);
  ok('EV loss drops to a supporting row', popup.loss === '0.34bb', popup.loss);
  ok('a losing decision keeps its sign', popup.negative === '-74%', popup.negative);
  ok('no EV loss means no EV row', popup.lossRowHidden);
  ok('an unpriceable decision shows no score at all', popup.noScoreHidden);
  ok('the hand end reports the hand, not the session',
    popup.opened && popup.hand === '4%', `${popup.hand} (session was ${popup.sessionAvg}%)`);
  ok('and says how many decisions that is over',
    /6回の判定/.test(popup.counts), popup.counts);
  ok('and it is the only view open',
    popup.only.length === 1 && popup.only[0] === 'session-view' && popup.overlay,
    popup.only.join(','));
  ok('a hand the hero never acted in raises no popup', popup.silent === false);

  console.log('\nand the corner keeps the last twenty hands');
  ok('twenty-five hands average only the last twenty', popup.recent === 40,
    String(popup.recent));
  ok('the popup carries it too', /直近20ハンド 40%/.test(popup.counts), popup.counts);
  ok('and so does the corner', /直近20\s*40%/.test(popup.corner), popup.corner);
  ok('a banked hand is its own average', popup.banked === 70, String(popup.banked));
  // 19 of the 40s plus the new 70, which is 41.5 and prints as 42.
  ok('and it displaces the oldest of the twenty', popup.afterBank === 42,
    String(popup.afterBank));
  ok('a hand with no decisions banks nothing', popup.emptyBank === null,
    String(popup.emptyBank));

  /* The pot pill holds the street's opening pot so a bet can be read against
     it, and the score divides by the pot including that bet. Two readings of
     "the pot" that must not be collapsed into one: pointing scoringPot() at the
     pill's number would quietly rescale every mistake the app has ever graded,
     and nothing on screen would look wrong. */
  const pots = await page.evaluate(() => {
    const out = {};
    state.handOver = false;
    state.pf = null;
    state.committed = {};
    state.bets = { SB: '0.5', BB: '1' };
    out.preflop = potDisplay();

    state.pf = {};                       // the hand is postflop from here
    state.committed = { SB: 0.5, BB: 2.8, BTN: 2.8 };
    state.bets = { BB: '3.35' };
    out.liveStreet = potDisplay();
    out.scored = potTotal();

    closeStreet();                       // the bet is called, the street closes
    out.closed = potDisplay();

    state.bets = { BB: '8', BTN: '8' };
    state.handOver = true;
    out.finished = potDisplay();
    return out;
  });

  console.log('\nthe pot pill');
  ok('preflop stays live, blinds and all', pots.preflop === 1.5, String(pots.preflop));
  ok('a bet on the felt does not move the pill',
    Math.abs(pots.liveStreet - 6.1) < 1e-9, String(pots.liveStreet));
  ok('but the score still divides by the pot the bet is in',
    Math.abs(pots.scored - 9.45) < 1e-9, String(pots.scored));
  ok('closing the street folds the bet in',
    Math.abs(pots.closed - 9.45) < 1e-9, String(pots.closed));
  ok('and a finished hand shows the whole pot',
    Math.abs(pots.finished - 25.45) < 1e-9, String(pots.finished));

  ok('nothing threw along the way', errors.length === 0, errors.join(' | '));

  await browser.close();
  srv.close();
  console.log(`\n=== ${passed} passed, ${failures.length} failed ===`);
  process.exit(failures.length ? 1 : 0);
})();
