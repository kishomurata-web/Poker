/* Checks that a bet size can be told from the sizes either side of it.
 *
 * In the range grid the colour is all there is - the segments carry no text -
 * so two sizes painted the same colour are not a hard distinction, they are no
 * distinction. That is what a fixed four-colour ramp did to a turn menu with
 * six sizes: the fourth, fifth and sixth were one colour.
 *
 * The distances here are CIEDE2000 under normal vision and under both
 * red-green dichromacies, which is what the ramp in index.html was chosen
 * against. They are floors, not targets - a change that reads better to the
 * eye and still clears them is fine.
 *
 *   node test_colors.js
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

/* ---- colour maths, kept here so the app does not carry it ---- */

const hex2rgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const lin = (c) => (c / 255 <= 0.04045 ? c / 255 / 12.92 : ((c / 255 + 0.055) / 1.055) ** 2.4);
const RGB2XYZ = [[0.4124564, 0.3575761, 0.1804375],
                 [0.2126729, 0.7151522, 0.0721750],
                 [0.0193339, 0.1191920, 0.9503041]];
const WP = [0.95047, 1, 1.08883];
// Vienot 1999, applied to linear RGB.
const DEUT = [[0.625, 0.375, 0], [0.7, 0.3, 0], [0, 0.3, 0.7]];
const PROT = [[0.1115, 0.8885, 0], [0.1115, 0.8885, 0], [0, 0, 1]];

function labOf(hex, M) {
  let rgb = hex2rgb(hex).map(lin);
  if (M) rgb = M.map((row) => Math.min(1, Math.max(0, row.reduce((s, m, i) => s + m * rgb[i], 0))));
  const xyz = RGB2XYZ.map((row) => row.reduce((s, m, i) => s + m * rgb[i], 0));
  const f = (t) => (t > 216 / 24389 ? Math.cbrt(t) : (841 / 108) * t + 4 / 29);
  const [fx, fy, fz] = xyz.map((v, i) => f(v / WP[i]));
  return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
}

function de2000([L1, a1, b1], [L2, a2, b2]) {
  const C1 = Math.hypot(a1, b1), C2 = Math.hypot(a2, b2), Cb = (C1 + C2) / 2;
  const G = 0.5 * (1 - Math.sqrt(Cb ** 7 / (Cb ** 7 + 25 ** 7)) || 0);
  const a1p = (1 + G) * a1, a2p = (1 + G) * a2;
  const C1p = Math.hypot(a1p, b1), C2p = Math.hypot(a2p, b2);
  const deg = (r) => ((r * 180) / Math.PI + 360) % 360;
  const h1p = C1p ? deg(Math.atan2(b1, a1p)) : 0;
  const h2p = C2p ? deg(Math.atan2(b2, a2p)) : 0;
  const dLp = L2 - L1, dCp = C2p - C1p;
  let dhp = 0;
  if (C1p * C2p !== 0) {
    dhp = h2p - h1p;
    if (Math.abs(dhp) > 180) dhp -= 360 * Math.sign(dhp);
  }
  const dHp = 2 * Math.sqrt(C1p * C2p) * Math.sin((dhp * Math.PI) / 360);
  const Lbp = (L1 + L2) / 2, Cbp = (C1p + C2p) / 2;
  let hbp = h1p + h2p;
  if (C1p * C2p !== 0) {
    hbp = Math.abs(h1p - h2p) <= 180 ? (h1p + h2p) / 2
      : (h1p + h2p < 360 ? (h1p + h2p + 360) / 2 : (h1p + h2p - 360) / 2);
  }
  const rad = (d) => (d * Math.PI) / 180;
  const T = 1 - 0.17 * Math.cos(rad(hbp - 30)) + 0.24 * Math.cos(rad(2 * hbp))
    + 0.32 * Math.cos(rad(3 * hbp + 6)) - 0.2 * Math.cos(rad(4 * hbp - 63));
  const dth = 30 * Math.exp(-(((hbp - 275) / 25) ** 2));
  const Rc = 2 * Math.sqrt(Cbp ** 7 / (Cbp ** 7 + 25 ** 7)) || 0;
  const Sl = 1 + (0.015 * (Lbp - 50) ** 2) / Math.sqrt(20 + (Lbp - 50) ** 2);
  const Sc = 1 + 0.045 * Cbp, Sh = 1 + 0.015 * Cbp * T;
  const Rt = -Math.sin(rad(2 * dth)) * Rc;
  return Math.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2
    + Rt * (dCp / Sc) * (dHp / Sh));
}

const VIS = [null, DEUT, PROT];
const apart = (x, y) => Math.min(...VIS.map((M) => de2000(labOf(x, M), labOf(y, M))));
const lightness = (hex) => labOf(hex)[0];

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
  await page.waitForFunction('typeof actionColorFor === "function"', null, { timeout: 15000 });

  /* An action is [code, type, betsize, allin, ...]; only the first four
     matter to the colour. */
  const painted = await page.evaluate(() => {
    const raise = (i) => ['R' + i, 'RAISE', String(i), false];
    const out = { menus: {}, others: {} };
    for (let n = 1; n <= 8; n++) {
      const sizes = Array.from({ length: n }, (_, i) => raise(i + 1));
      out.menus[n] = sizes.map((a) => actionColorFor(a, sizes));
    }
    const sizes = [raise(1), raise(2)];
    out.others.fold = actionColorFor(['F', 'FOLD', '0', false], sizes);
    out.others.check = actionColorFor(['X', 'CHECK', '0', false], sizes);
    out.others.call = actionColorFor(['C', 'CALL', '0', false], sizes);
    out.others.allin = actionColorFor(['RAI', 'RAISE', '30', true], sizes);
    return out;
  });

  console.log('\nevery size on a menu gets its own colour');
  for (let n = 2; n <= 6; n++) {
    const ramp = painted.menus[n];
    ok(`${n} sizes, ${n} colours`, new Set(ramp).size === n, ramp.join(' '));
  }

  console.log('\nand neighbouring sizes stay apart, in colour and in dichromacy');
  for (let n = 2; n <= 6; n++) {
    const ramp = painted.menus[n];
    const gaps = ramp.slice(1).map((c, i) => apart(ramp[i], c));
    const floor = n <= 4 ? 8 : 4;
    ok(`${n} sizes: worst neighbouring gap >= ${floor}`,
      Math.min(...gaps) >= floor,
      `${ramp.join(' ')}  ->  ${gaps.map((g) => g.toFixed(1)).join(', ')}`);
  }

  console.log('\na bigger bet is never a lighter colour');
  for (let n = 2; n <= 6; n++) {
    const ramp = painted.menus[n];
    const ls = ramp.map(lightness);
    ok(`${n} sizes darken all the way down`,
      ls.every((l, i) => i === 0 || l < ls[i - 1] - 1),
      ls.map((l) => l.toFixed(0)).join(' > '));
  }

  console.log('\nand no size is mistakable for a different action');
  const others = Object.entries(painted.others);
  const worst = [];
  for (let n = 2; n <= 6; n++) {
    painted.menus[n].forEach((c) => {
      others.forEach(([name, o]) => worst.push([apart(c, o), c, name]));
    });
  }
  worst.sort((a, b) => a[0] - b[0]);
  ok('nothing lands on fold, check, call or all-in',
    worst[0][0] >= 7, `${worst[0][1]} vs ${worst[0][2]} = ${worst[0][0].toFixed(1)}`);

  console.log('\nand a menu longer than the ramp still paints');
  ok('7 sizes paint without throwing', painted.menus[7].length === 7);
  ok('8 sizes paint without throwing', painted.menus[8].length === 8);

  ok('nothing threw along the way', errors.length === 0, errors.join(' | '));

  await browser.close();
  srv.close();
  console.log(`\n=== ${passed} passed, ${failures.length} failed ===`);
  process.exit(failures.length ? 1 : 0);
})();
