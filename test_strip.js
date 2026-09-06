/* Checks the action strip reads back the hand that was played.
 *
 * It replaced a grid of streets by positions, which spent eight of its nine
 * columns on dots once the hand went heads-up postflop, and grew a row when the
 * turn arrived - and the strip sits above the felt, so growing it shrank the
 * table and moved every seat. The height assertion here is that bug's fence.
 *
 * The hand below is the one in the reference: six folds to a button open, the
 * blinds' own decisions, then heads-up play with the folded seats simply gone.
 *
 *   node test_strip.js
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
  // A phone, because the strip only has to scroll on one.
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(`http://127.0.0.1:${srv.address().port}/index.html`, { waitUntil: 'load' });
  await page.waitForFunction(
    'typeof recordHistory === "function" && typeof markStreet === "function"',
    null, { timeout: 15000 });

  const run = await page.evaluate(() => {
    // The stub index.json carries no depths, so the app never leaves its
    // loading screen on its own - and an element inside a hidden screen has no
    // width or height, which would make every measurement below pass on zero.
    document.getElementById('loading').style.display = 'none';
    document.getElementById('app').style.display = '';

    const SEATS = ['UTG', 'UTG1', 'LJ', 'HJ', 'CO', 'BTN', 'SB', 'BB'];
    state.spot = { positions: SEATS, stacks: SEATS.map(() => 40), category: 'chipev' };
    state.stacks = {};
    SEATS.forEach((p) => { state.stacks[p] = 40; });
    state.heroPos = 'BB';
    state.handOver = false;
    state.pf = null;
    state.timeline = [];
    state.committed = {};
    state.bets = { SB: '0.5', BB: '1' };      // the blinds are already in
    document.getElementById('act-history').style.display = '';

    const fold = ['F', 'FOLD', '0.000', false, null, true, false, false, null, false];
    const call = ['C', 'CALL', '0.000', false, null, false, true, false, null, false];
    const check = ['X', 'CHECK', '0.000', false, null, false, false, false, null, false];
    const open = ['R2.3', 'RAISE', '2.300', false, null, false, false, false, null, false];

    const out = { heights: [] };
    const strip = document.getElementById('act-history');
    const act = (pos, a) => {
      state.actingPos = pos;
      recordHistory('preflop', pos, a);
      out.heights.push(strip.offsetHeight);
      if (a[1] !== 'FOLD') state.bets[pos] = a[1] === 'CALL' ? '2.3' : a[2];
    };

    ['UTG', 'UTG1', 'LJ', 'HJ', 'CO'].forEach((p) => act(p, fold));
    act('BTN', open);
    act('SB', fold);
    act('BB', call);
    out.preflopText = strip.textContent;

    closeStreet();                             // the flop is dealt
    state.pf = { board: ['Ks', '9d', '7h'] };
    markStreet('FLOP', state.pf.board);
    state.actingPos = 'BB'; recordHistory('flop', 'BB', check);
    state.actingPos = 'BTN'; recordHistory('flop', 'BTN', check);
    markStreet('TURN', ['Kc']);
    state.actingPos = 'BB';
    renderHistory();
    out.heights.push(strip.offsetHeight);

    out.cells = [...strip.children].map((c) => ({
      street: c.classList.contains('as-street'),
      tag: c.tagName,
      pos: (c.querySelector('.as-pos') || {}).textContent,
      stack: (c.querySelector('.as-stack') || {}).textContent,
      act: (c.querySelector('.as-act') || {}).textContent,
      kind: (c.querySelector('.as-act') || { className: '' }).className,
      text: c.textContent,
      cards: c.querySelectorAll('.card').length,
      current: c.classList.contains('current'),
      hero: c.classList.contains('hero'),
    }));
    out.scrollWidth = strip.scrollWidth;
    out.clientWidth = strip.clientWidth;
    out.rowHeight = strip.getBoundingClientRect().height;

    // the hand ends
    state.handOver = true;
    updateSeatActing(null);
    out.afterEnd = [...strip.children].map((c) => c.textContent).join('|');

    // a chip that can be navigated back to, which is what study mode needs
    renderActionStrip(strip, [{ pos: 'BB', t: 'Check', kind: 'check', onPick: () => {} }]);
    out.pickable = strip.firstChild.tagName;
    return out;
  });

  const cells = run.cells;
  const chips = cells.filter((c) => !c.street);
  const streets = cells.filter((c) => c.street);

  console.log('\nthe hand reads back in the order it was played');
  // Ten actions were played; the eleventh chip is the question being asked, and
  // is checked further down.
  ok('every action is a chip and nothing else is',
    chips.length === 11, `${chips.length} chips: ${chips.map((c) => c.pos).join(' ')}`);
  ok('starting with the first player to act', chips[0].pos === 'UTG', chips[0].pos);
  ok('the button opens', chips[5].pos === 'BTN' && chips[5].act === 'Raise 2.3',
    `${chips[5].pos} ${chips[5].act}`);
  ok('the blinds answer in order',
    chips[6].pos === 'SB' && chips[7].pos === 'BB' && chips[7].act === 'Call',
    `${chips[6].pos} ${chips[7].pos} ${chips[7].act}`);

  console.log('\nwith the stack each choice was made against');
  ok('a full stack before the blinds are posted', chips[0].stack === '40', chips[0].stack);
  ok('the button still has 40 when it opens', chips[5].stack === '40', chips[5].stack);
  ok('the small blind is down its 0.5', chips[6].stack === '39.5', chips[6].stack);
  ok('the big blind is down its 1', chips[7].stack === '39', chips[7].stack);
  ok("and the caller's stack is read before the call, not after",
    chips[7].stack === '39' && chips[8].stack === '37.7',
    `${chips[7].stack} then ${chips[8].stack}`);

  console.log('\nthe streets are marked where they fell');
  ok('two of them', streets.length === 2, String(streets.length));
  ok('the flop arrives with three cards',
    streets[0].text.startsWith('FLOP') && streets[0].cards === 3,
    `${streets[0].text} / ${streets[0].cards} cards`);
  // 0.5 + 2.3 + 2.3, since this table posts blinds and no ante.
  ok('and the pot it opened with', streets[0].text.includes('5.1'), streets[0].text);
  ok('the turn arrives with one', streets[1].text.startsWith('TURN') && streets[1].cards === 1,
    `${streets[1].text} / ${streets[1].cards} cards`);
  ok('and a check-through leaves the pot where it was',
    streets[1].text.includes('5.1'), streets[1].text);

  console.log('\nand a seat that folded preflop is simply gone');
  const afterFlop = cells.slice(cells.findIndex((c) => c.street)).filter((c) => !c.street);
  ok('only the two players still in appear after the flop',
    afterFlop.every((c) => c.pos === 'BB' || c.pos === 'BTN'),
    afterFlop.map((c) => c.pos).join(' '));
  ok('the folded seats are not carried as empty slots',
    !afterFlop.some((c) => ['UTG', 'UTG1', 'LJ', 'HJ', 'CO', 'SB'].includes(c.pos)));

  console.log('\nthe line ends on the decision in front of the player');
  const last = chips[chips.length - 1];
  ok('the player to act closes it', last.pos === 'BB' && last.current, JSON.stringify(last));
  ok('and is asked, not reported', last.act === 'アクションをする', last.act);
  ok('the hero is marked as the hero', last.hero);
  ok('a finished hand asks nobody', !/アクションをする/.test(run.afterEnd), run.afterEnd);

  console.log('\nand it is one line that scrolls, not a block that grows');
  ok('it overflows sideways on a phone', run.scrollWidth > run.clientWidth,
    `${run.scrollWidth} > ${run.clientWidth}`);
  ok('every entry left the height alone',
    new Set(run.heights).size === 1, run.heights.join(','));
  ok('and that height is one row', run.rowHeight > 0 && run.rowHeight <= 34,
    String(run.rowHeight));

  console.log('\nand a chip can be a way back');
  ok('an entry with a handler is a button', run.pickable === 'BUTTON', run.pickable);

  ok('nothing threw along the way', errors.length === 0, errors.join(' | '));

  await browser.close();
  srv.close();
  console.log(`\n=== ${passed} passed, ${failures.length} failed ===`);
  process.exit(failures.length ? 1 : 0);
})();
