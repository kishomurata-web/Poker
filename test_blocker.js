/* Checks that a tap on the blocker grid opens the combos behind the cell.
 *
 * The cell can only show a mean, and the mean is exactly what a blocker score
 * must not be read as - Kh Qh and Ks Qs share a cell and block different cards.
 * So the assertions are about the individual combos: that the right ones are
 * listed, that the ones missing are accounted for by name, and that the mean
 * printed over them is the same number the cell was painted with.
 *
 * Drives the real index.html in a browser rather than extracting the functions,
 * because what is being tested is a click handler and what it puts in the DOM.
 * The app is served with an empty depth list, which is enough for it to finish
 * starting up; the node under test is built by hand in the page.
 *
 *   node test_blocker.js
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

const TYPES = { '.html': 'text/html', '.js': 'text/javascript',
                '.json': 'application/json', '.webmanifest': 'application/manifest+json' };

(async () => {
  const srv = http.createServer((req, res) => {
    const url = req.url.split('?')[0];
    // Enough of a manifest for start-up to complete. No depth means no data
    // fetch, which is what keeps this test independent of the collection.
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
    'typeof HAND_INDEX !== "undefined" && HAND_INDEX && HAND_INDEX.size === 169',
    null, { timeout: 15000 });

  // KQs on a board holding Qs: four combos, one of them dealt away, one the
  // site never scored, two with scores that are deliberately far apart so an
  // averaged answer cannot pass for a per-combo one.
  const setup = await page.evaluate(() => {
    pfEnsureClassMaps();
    const idx = (label) => PF_COMBO_CARDS.findIndex((p) => p.join(' ') === label);
    const plane = new Uint16Array(1326);
    const KcQc = idx('Kc Qc'), KdQd = idx('Kd Qd'), KhQh = idx('Kh Qh'), KsQs = idx('Ks Qs');
    plane[KcQc] = 9;        // stored +1: a real score of 8
    plane[KdQd] = 4;        // a real score of 3
    plane[KhQh] = 0;        // the source's -1: not scored
    plane[KsQs] = 11;       // scored, but the board holds Qs so it never counts
    const node = { _blocker: plane };
    const board = ['Qs', '7h', '2d'];
    const grid = document.createElement('div');
    const detail = document.createElement('div');
    detail.className = 'cell-detail';
    document.body.appendChild(grid);
    document.body.appendChild(detail);
    window.__t = { node, board, grid, detail, KcQc, KdQd, KhQh, KsQs };
    return { KcQc, KdQd, KhQh, KsQs, cellMean: blockerCells(node, board, 'blocker')[HAND_INDEX.get('KQs')] };
  });

  ok('the cell itself averages only the two scored, unblocked combos',
    Math.abs(setup.cellMean - 5.5) < 1e-9, String(setup.cellMean));

  // Rendered with no hero, so nothing is opened for us and the tap is the
  // thing under test.
  const tapped = await page.evaluate(() => {
    const t = window.__t;
    renderBlockerGrid(t.grid, t.detail, t.node, t.board, 'blocker', null, null);
    const before = t.detail.textContent;
    const cells = [...t.grid.querySelectorAll('.hand-cell')];
    const cell = cells.find((c) => c.querySelector('.hand-label').textContent === 'KQs');
    const shown = cell.querySelector('.bs-num') ? cell.querySelector('.bs-num').textContent : null;
    cell.click();
    const rows = [...t.detail.querySelectorAll('.cd-combo')].map((r) => ({
      name: r.querySelector('.cc-name').textContent,
      score: r.querySelector('.cc-bs').textContent,
      hero: r.classList.contains('hero'),
      // style.flex reads back as the expanded shorthand ("8 1 0%"), so only
      // the grow factor is the number that was set.
      fill: r.querySelector('.mseg').style.flex.split(' ')[0],
    }));
    return {
      before, shown,
      picked: cell.classList.contains('picked'),
      head: t.detail.querySelector('.cd-hand').textContent,
      census: t.detail.querySelector('.cd-share').textContent,
      title: t.detail.querySelector('.mix-title').textContent,
      rows,
    };
  });

  ok('before any tap the panel says a tap is what opens the combos',
    /タップ/.test(tapped.before), tapped.before);
  ok('the cell is painted with the mean', tapped.shown === '5.5', String(tapped.shown));
  ok('tapping marks the cell as picked', tapped.picked === true);
  ok('the panel names the hand and the score being shown',
    tapped.head === 'KQs のブロッカースコア', tapped.head);
  ok('only the scored, unblocked combos are listed',
    tapped.rows.length === 2, JSON.stringify(tapped.rows));
  ok('and they are the right two, with their own scores',
    tapped.rows.length === 2
    && tapped.rows[0].name === 'K♣ Q♣' && tapped.rows[0].score === '8.0'
    && tapped.rows[1].name === 'K♦ Q♦' && tapped.rows[1].score === '3.0',
    JSON.stringify(tapped.rows));
  // The whole point of the panel: two combos of one class, six points apart.
  ok('the bars are drawn against a fixed 0..10, not against each other',
    tapped.rows.length === 2 && tapped.rows[0].fill === '8' && tapped.rows[1].fill === '3',
    JSON.stringify(tapped.rows.map((r) => r.fill)));
  ok('the two missing combos are accounted for by name, not just absent',
    tapped.census === '4コンボ中 2（ボード被り 1、スコアなし 1）', tapped.census);
  ok('the mean over the rows is the same number the cell was painted with',
    /平均 5\.5/.test(tapped.title), tapped.title);

  // A hand the site scored nothing for has to say so rather than open empty.
  const empty = await page.evaluate(() => {
    const t = window.__t;
    const cells = [...t.grid.querySelectorAll('.hand-cell')];
    const cell = cells.find((c) => c.querySelector('.hand-label').textContent === '72o');
    cell.click();
    return {
      head: t.detail.querySelector('.cd-hand').textContent,
      census: t.detail.querySelector('.cd-share').textContent,
      note: (t.detail.querySelector('.cd-placeholder') || {}).textContent || '',
      rows: t.detail.querySelectorAll('.cd-combo').length,
    };
  });
  ok('a cell with nothing scored still answers the tap',
    empty.head === '72o のブロッカースコア' && empty.rows === 0, JSON.stringify(empty));
  ok('and says why it is empty', /採点されたコンボがありません/.test(empty.note), empty.note);

  // With a hero, the grid opens on their cell the way the strategy grid does,
  // and their own combo is the row marked in it.
  const hero = await page.evaluate(() => {
    const t = window.__t;
    renderBlockerGrid(t.grid, t.detail, t.node, t.board, 'blocker', 'KQs', t.KdQd);
    const rows = [...t.detail.querySelectorAll('.cd-combo')].map((r) => ({
      name: r.querySelector('.cc-name').textContent,
      hero: r.classList.contains('hero'),
    }));
    return { head: (t.detail.querySelector('.cd-hand') || {}).textContent || '', rows };
  });
  ok('the grid opens on the hero cell without being tapped',
    hero.head === 'KQs のブロッカースコア', hero.head);
  ok("and the hero's own combo is the row marked in it",
    hero.rows.length === 2 && hero.rows[1].hero === true && hero.rows[0].hero === false,
    JSON.stringify(hero.rows));

  ok('nothing threw along the way', errors.length === 0, errors.join(' | '));

  await browser.close();
  srv.close();
  console.log(`\n=== ${passed} passed, ${failures.length} failed ===`);
  process.exit(failures.length ? 1 : 0);
})();
