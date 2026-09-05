// Can the app still load its data, and still save it for offline use?
//
//   node test_offline.js
//
// The real index.html and the real sw.js, in a real Chromium, with a small
// dataset served from a local server. Everything before this was a unit test on
// a function; this is the thing the phone actually does.
const http = require('http');
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');
const { chromium } = require('playwright');

let pass = 0; let fail = 0;
const ok = (n, c, d) => { if (c) { pass++; console.log('  PASS  ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (d ? ' - ' + d : '')); } };

const ROOT = fs.mkdtempSync('/tmp/offtest-');

// How the server behaves for the postflop data files. The point of the test is
// that these cases must look different on screen; before, all of them read as
// "0 / 299" and stayed there.
//
//   hang   the server never answers at all
//   stall  the server answers, sends part of the file, and then stops - which
//          is the case the timeout used to miss completely, because it was
//          cleared as soon as the headers arrived
//   strict a server that will only answer one data request at a time and
//          rejects the rest - which is what a small PC web server handed four
//          at once may well do, and the reason a parallel save can fail where
//          a serial one did not
const MODE = process.argv.includes('--fail') ? 'fail'
  : process.argv.includes('--hang') ? 'hang'
    : process.argv.includes('--stall') ? 'stall'
      : process.argv.includes('--strict') ? 'strict'
        : process.argv.includes('--crash') ? 'crash'
          : process.argv.includes('--mute') ? 'mute'
            : process.argv.includes('--revalidate') ? 'revalidate'
              : process.argv.includes('--slow') ? 'slow'
                : process.argv.includes('--probe') ? 'probe'
                  : process.argv.includes('--dead') ? 'dead'
                    : process.argv.includes('--die') ? 'die' : 'ok';

const NFILES = 12;
function writeDataset(stamp) {
  const dir = path.join(ROOT, 'postflop', '40');
  fs.mkdirSync(dir, { recursive: true });
  const nodes = {
    'FLOP|flop_OOP': {
      side: 'oop', pot: 6.1,
      actions: [{ code: 'X', type: 'CHECK', betsize: 0, allin: false, frac: 0, next: null }],
      reach: 'x', strat: 'x', loss: 'x',
    },
  };
  const files = {};
  for (let i = 0; i < NFILES; i++) {
    const flop = `7s3h${i}d`;
    const name = `BTN_vs_BB__${flop}.json.gz`;
    fs.writeFileSync(path.join(dir, name),
      zlib.gzipSync(JSON.stringify({ pair: 'BTN_vs_BB', flop, nodes })));
    files[flop] = { file: name, nodes: 1 };
  }
  fs.writeFileSync(path.join(dir, 'index.json'), JSON.stringify({
    combos: true, depth: 40.125,
    pairs: { BTN_vs_BB: { preflop: 'F-F-F-F-F-R2.3-F-C', oop: 'BB', ip: 'BTN' } },
    sizes: { BTN_vs_BB: { c33: 'R2' } }, handOrder: [],
    files: { BTN_vs_BB: files },
  }));
  fs.writeFileSync(path.join(ROOT, 'postflop', 'index.json'), JSON.stringify({
    version: 2, generated: stamp,
    depths: [{ id: '40', label: '40BB', depth: 40.125, generated: stamp, bytes: 1000 }],
  }));
}

(async () => {
  // The old worker has no per-fetch timeout, so on a hung file it hangs - which
  // is the defect the new one fixes, not something to assert against here.
  if ((MODE === 'crash' || MODE === 'mute') && !process.argv.includes('--new')) {
    console.log(`\n  --${MODE} needs --new: it tests reporting the old worker does not have.\n`);
    process.exit(0);
  }
  if (MODE === 'die' && !process.argv.includes('--new')) {
    console.log('\n  --die needs --new: the old worker cannot be resumed.\n');
    process.exit(0);
  }
  if (MODE === 'dead' && !process.argv.includes('--new')) {
    console.log('\n  --dead needs --new: the old worker has no give-up rule.\n');
    process.exit(0);
  }
  if (MODE === 'probe' && !process.argv.includes('--new')) {
    console.log('\n  --probe needs --new: the old worker has no PROBE handler.\n');
    process.exit(0);
  }
  if (MODE === 'slow' && !process.argv.includes('--new')) {
    console.log('\n  --slow needs --new: the old worker sends no heartbeat to test.\n');
    process.exit(0);
  }
  if (MODE === 'revalidate' && !process.argv.includes('--new')) {
    console.log('\n  --revalidate needs --new: the old worker re-downloads the page every time,\n'
      + '  which is the behaviour being fixed rather than a thing to test.\n');
    process.exit(0);
  }
  if (MODE === 'strict' && !process.argv.includes('--new')) {
    console.log('\n  --strict needs --new: the old worker never fetches in parallel.\n');
    process.exit(0);
  }
  if ((MODE === 'hang' || MODE === 'stall') && !process.argv.includes('--new')) {
    console.log('\n  --hang needs --new: the old worker has no timeout to test.\n');
    process.exit(0);
  }
  // The old worker: what a device that has not picked up the new one is still
  // running. It has no DROP_DEPTH handler, which is the point.
  let html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
  // The watchdog waits 20s for the worker to acknowledge and 180s for it to
  // keep talking - right on a phone, far too long for a test. The code under
  // test is the same code either way.
  if (MODE === 'mute') html = html.replace('OFF.accepted ? 180 : 20', 'OFF.accepted ? 6 : 3');
  // Twelve seconds of silence counts as stalled, against one file that takes
  // twenty. Without a heartbeat that file alone trips the watchdog; with one
  // every five seconds it cannot. Turning the deadline down rather than the
  // heartbeat up keeps the thing under test - the worker - exactly as shipped.
  if (MODE === 'slow') html = html.replace('OFF.accepted ? 180 : 20', 'OFF.accepted ? 12 : 20');
  // Eight seconds of silence, not the thirty a five-second pulse earns. The
  // recovery under test is the same either way; only the waiting is shortened.
  if (MODE === 'die') html = html.replace('OFF.accepted ? OFF.stallAfter : 20', 'OFF.accepted ? 8 : 20');
  fs.writeFileSync(path.join(ROOT, 'index.html'), html);
  // Default: the old worker, which is what a device that has not picked up the
  // new one is still running. --new runs the current one, to check that the
  // path where the drop does work is not broken by the timeout.
  const NEW = process.argv.includes('--new');
  const WORKER = NEW ? 'sw.js' : 'sw_before.js';
  console.log(`\n  worker under test: ${WORKER}\n`);
  let sw = fs.readFileSync(path.join(__dirname, WORKER), 'utf8');
  // 120s is right on a phone and far too long for a test, so the hang case runs
  // the same code with the timeout turned down.
  if (MODE === 'hang' || MODE === 'stall' || MODE === 'dead') {
    sw = sw.replace(/HEADER_TIMEOUT_MS = \d+/, 'HEADER_TIMEOUT_MS = 3000')
      .replace(/STALL_TIMEOUT_MS = \d+/, 'STALL_TIMEOUT_MS = 3000')
      .replace(/FETCH_TIMEOUT_MS = \d+/, 'FETCH_TIMEOUT_MS = 20000');
  }
  // A bug in the save itself, thrown where no try/catch of its own can see it.
  // This is the shape of fault that reached the user as a completely blank
  // panel: the promise inside waitUntil rejected and nobody was told.
  if (MODE === 'crash') {
    sw = sw.replace("say({ url, phase: 'start' });",
      "say({ url, phase: 'start' }); if (/7s3h3d/.test(url)) throw new Error('injected crash');");
  }
  // A worker that stops dead in the middle of a save - which is what a phone
  // browser does to a service worker that has been running too long, and is
  // the fault the page now recovers from instead of reporting. Once only, so
  // the resumed run can get past it and the test can see it finish.
  if (MODE === 'die') {
    sw = sw.replace('const CACHE_VERSION', 'let diedOnce = false;\nconst CACHE_VERSION')
      .replace("say({ url, phase: 'start' });",
        "say({ url, phase: 'start' });"
        + " if (!diedOnce && /7s3h5d/.test(url)) { diedOnce = true; clearInterval(beat);"
        + " await new Promise(() => {}); }");
  }
  // A worker that hears the request and never says anything at all.
  if (MODE === 'mute') sw = sw.replace("if (msg.type === 'CACHE_URLS') {", "if (false) {");
  fs.writeFileSync(path.join(ROOT, 'sw.js'), sw);
  fs.writeFileSync(path.join(ROOT, 'manifest.webmanifest'), '{"name":"t"}');
  fs.writeFileSync(path.join(ROOT, 'icon.svg'), '<svg xmlns="http://www.w3.org/2000/svg"/>');
  writeDataset('2026-09-01 10:00');

  // What the save actually costs is round trips, so the fix for a slow save is
  // to have more than one in the air at a time. That is only visible if the
  // server is slow enough for them to overlap, and only provable if the server
  // counts them.
  let inFlight = 0;
  let maxInFlight = 0;
  let refused = 0;
  // Bytes of each non-data file actually put on the wire, and how often the
  // server got to answer "unchanged" instead. The pair is the measurement:
  // a page load that costs a 304 rather than the page is the whole fix.
  const bodyBytes = {};
  const notModified = {};
  let shellSilent = false;
  let shellAborted = 0;
  const DELAY_MS = 120;

  const server = http.createServer((req, res) => {
    let rel = decodeURIComponent(req.url.split('?')[0]);
    if (rel === '/') rel = '/index.html';
    // The data files misbehave on demand; the shell and the indexes always
    // work, so the app still loads and the panel is reachable.
    const isData = /\.json\.gz$/.test(rel);
    // A PC that has gone quiet on the shell. The launch timeout should end the
    // wait AND the request: the worker used to only stop listening, leaving the
    // whole page still coming down a link the save needed.
    if (shellSilent && !isData) {
      req.on('close', () => { shellAborted++; });
      return;
    }
    if (isData) {
      if (MODE === 'fail') { res.writeHead(500); res.end('no'); return; }
      if (MODE === 'hang' && rel.includes('7s3h0d')) return;  // never answers
      // Every data file, not one: a PC that is asleep, off the tailnet, or
      // serving a different folder answers none of them, and that is the run
      // that used to spend 30s per file working through all of them.
      if (MODE === 'dead') return;
      // Answers, then stops mid-body. The response headers arrive normally, so
      // fetch() resolves and everything looks fine; the file never finishes.
      if (MODE === 'stall' && rel.includes('7s3h0d')) {
        res.writeHead(200, { 'content-type': 'application/octet-stream', 'content-length': '99999' });
        // Enough to be measurable, so the failure can report how far it got.
        res.write(Buffer.alloc(4096, 7));
        return;  // the rest never comes, and the response is never ended
      }
    }
    // Only one data file at a time; everything beyond that is turned away.
    // A serial save never notices; a parallel one fails on three files in
    // four unless it backs off and tries them again.
    if (isData && MODE === 'strict' && inFlight > 0) {
      refused++;
      res.writeHead(503); res.end('busy'); return;
    }
    const p = path.join(ROOT, rel);
    if (!fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); res.end('no'); return; }
    // A real static server - serve_app.py included - offers Last-Modified and
    // honours If-Modified-Since. Without that here, every request costs the
    // whole file and there is no way to measure the thing this mode is about:
    // whether the worker ASKS whether the page changed, or just downloads it.
    if (!isData) {
      const mtime = fs.statSync(p).mtime;
      const stamp = mtime.toUTCString();
      const since = req.headers['if-modified-since'];
      // Second resolution, as the header format has.
      if (since && Math.floor(mtime.getTime() / 1000) <= Math.floor(Date.parse(since) / 1000)) {
        notModified[rel] = (notModified[rel] || 0) + 1;
        res.writeHead(304, { 'last-modified': stamp });
        res.end();
        return;
      }
      bodyBytes[rel] = (bodyBytes[rel] || 0) + fs.statSync(p).size;
      res.setHeader('last-modified', stamp);
    }
    const send = () => {
      res.writeHead(200, {
        // Content-Length, as any real static server sends for a file on disk.
        // It is where the save reads its byte count from now that it streams
        // straight into the cache instead of buffering the file to measure it.
        'content-length': fs.statSync(p).size,
        'content-type': p.endsWith('.js') ? 'text/javascript'
          : p.endsWith('.json') || p.endsWith('.webmanifest') ? 'application/json'
            : p.endsWith('.svg') ? 'image/svg+xml'
              : p.endsWith('.gz') ? 'application/octet-stream' : 'text/html',
      });
      fs.createReadStream(p).pipe(res).on('close', () => {
        if (isData) inFlight--;
      });
    };
    if (isData) {
      inFlight++;
      maxInFlight = Math.max(maxInFlight, inFlight);
      // One file that is slow but perfectly healthy - a big file on a mobile
      // link, which is the normal case here and must not be mistaken for a
      // worker that has died. Still well inside HEADER_TIMEOUT_MS, so the
      // worker itself has no reason to give up on it.
      const slow = MODE === 'slow' && rel.includes('7s3h0d');
      setTimeout(send, slow ? 20000 : DELAY_MS);
    } else send();
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${server.address().port}/`;

  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));

  // First visit: register the old worker and let the app load normally.
  await page.goto(base, { waitUntil: 'load' });
  await page.evaluate(() => navigator.serviceWorker.register('sw.js')
    .then(() => navigator.serviceWorker.ready));
  await page.waitForFunction('window.PF_DEPTHS !== null && window.PF_DEPTHS !== undefined', null, { timeout: 20000 })
    .catch(() => {});
  const first = await page.evaluate('Array.isArray(PF_DEPTHS) ? PF_DEPTHS.length : String(PF_DEPTHS)');
  ok('the app loads its data on a first visit', first === 1, `PF_DEPTHS = ${first}`);

  // Now the dataset is converted again. The device still runs the old worker,
  // which does not answer DROP_DEPTH - and the page waits for that answer
  // before it will finish loading the index.
  writeDataset('2026-09-02 11:00');
  const page2 = await ctx.newPage();
  page2.on('pageerror', (e) => errors.push(e.message));
  await page2.goto(base, { waitUntil: 'load' });
  let loaded = true;
  await page2.waitForFunction('Array.isArray(PF_DEPTHS) && PF_DEPTHS.length > 0', null, { timeout: 15000 })
    .catch(() => { loaded = false; });
  ok('and still loads it after a re-conversion, with the old worker in place',
    loaded, 'PF_DEPTHS never arrived: the drop message is never answered');

  if (loaded && MODE === 'probe') {
    // The question a failed save cannot answer: is the PC reachable at all?
    // The app opens from Cache Storage whether it is or not, so "the app works"
    // is no evidence either way - which is exactly how "PC sent nothing for 30s"
    // on one file came to be read as a problem with that file.
    //
    // Shortened only on the page's side; the worker's own deadline is the one
    // that ships.
    const reachable = await page2.evaluate(() => offAsk({ type: 'PROBE' }, null, 20000));
    console.log(`        PC reachable: ${JSON.stringify(reachable)}`);
    ok('with the PC answering, the probe says so and times it',
      reachable && reachable.ok === true && reachable.bytes > 0
      && typeof reachable.ms === 'number', JSON.stringify(reachable));

    // Now the PC goes away entirely - asleep, Tailscale down, server stopped.
    // All of those look the same from here, and all of them are "not reachable".
    shellSilent = true;
    const gone = await page2.evaluate(() => offAsk({ type: 'PROBE' }, null, 25000));
    console.log(`        PC gone:      ${JSON.stringify(gone)}`);
    ok('and with the PC gone it says that, rather than blaming a file',
      gone && gone.ok === false && /応答がありません/.test(gone.error || ''),
      JSON.stringify(gone));
    // The panel has to render the difference, not just receive it.
    const shown = await page2.evaluate(async () => {
      await offProbe(null);
      return document.getElementById('off-note').textContent;
    });
    console.log(`        panel says:   "${shown}"`);
    ok('and the panel names the PC as the thing that is unreachable',
      /PCに繋がりません/.test(shown), shown);
    shellSilent = false;
  } else if (loaded && MODE === 'revalidate') {
    // What a launch costs, measured rather than reasoned about.
    //
    // index.html is megabytes in the real app, and the shell is network-first
    // so that a new build can land. Fetched with `no-store` that meant the
    // whole page came down the wire on every single launch, to discover almost
    // every time that it was the same page - and over a phone link it could not
    // finish inside the 2.5s launch timeout either, so the download was thrown
    // away AND a real new build could never arrive through it. Both halves are
    // fixed by asking instead of downloading.
    const pageBefore = bodyBytes['/index.html'] || 0;
    const n304Before = notModified['/index.html'] || 0;
    await page2.reload({ waitUntil: 'load' });
    await page2.waitForFunction('Array.isArray(PF_DEPTHS) && PF_DEPTHS.length > 0', null, { timeout: 15000 })
      .catch(() => {});
    const sentOnReload = (bodyBytes['/index.html'] || 0) - pageBefore;
    const n304 = (notModified['/index.html'] || 0) - n304Before;
    console.log(`        page bytes sent on reload: ${sentOnReload}`);
    console.log(`        "unchanged" answers:       ${n304}`);
    ok('opening the app again asks whether the page changed', n304 > 0,
      `no If-Modified-Since reached the server (${n304} answered unchanged)`);
    ok('and does not download the page to find out it did not change',
      sentOnReload === 0, `${sentOnReload} bytes of index.html sent again`);

    // The other half: a build that really did change still has to arrive.
    fs.writeFileSync(path.join(ROOT, 'index.html'),
      fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8')
        .replace('<title>', '<title data-fresh="yes">'));
    // Through a plain reload, which is the path that carries it: the worker
    // asks, the answer this time is 200 rather than 304, and the new page is
    // both served and stored. Not reg.update() - that refetches sw.js, and
    // sw.js has not changed, so no install would run and nothing would be
    // proved about the page.
    const changedBefore = bodyBytes['/index.html'] || 0;
    await page2.reload({ waitUntil: 'load' });
    const servedNew = await page2.evaluate(
      () => !!document.querySelector('title[data-fresh="yes"]'));
    ok('but a page that really changed is fetched, so an update can still land',
      (bodyBytes['/index.html'] || 0) > changedBefore && servedNew,
      `sent ${(bodyBytes['/index.html'] || 0) - changedBefore} bytes, new page on screen: ${servedNew}`);

    // And the other half of the same fix. Giving up on a slow PC has to close
    // the request, not merely stop waiting for it: the old code left the page
    // still downloading in the background, once per launch, competing for the
    // handful of connections the browser allows and for a link the offline save
    // was trying to use. A timeout that does not cancel is not a timeout.
    shellSilent = true;
    const launched = Date.now();
    await page2.reload({ waitUntil: 'load' }).catch(() => {});
    const waited = Date.now() - launched;
    ok('a PC that goes quiet does not stop the app opening from its stored copy',
      await page2.evaluate(() => !!document.querySelector('title')), `waited ${waited}ms`);
    await new Promise((r) => setTimeout(r, 500));
    console.log(`        launch wait: ${waited}ms, requests dropped: ${shellAborted}`);
    ok('and the request it gave up on is actually cancelled, not left running',
      shellAborted > 0, 'the server never saw the connection close');
    shellSilent = false;
  } else if (loaded) {
    // The offline save is what the phone is actually for.
    inFlight = 0; maxInFlight = 0;
    const saved = await page2.evaluate(async (mode) => {
      await offRefresh();
      const btns = [...document.querySelectorAll('#off-saves button')];
      if (!btns.length) return { err: 'no save button' };
      // The watchdog's verdict has to be caught as it happens: it writes into
      // the same element the progress counter does, so by the end of a save
      // that recovered there is nothing left on screen to show it ever fired.
      const stalls = [];
      const resumed = [];
      const target = document.getElementById('off-state');
      new MutationObserver(() => {
        if (/応答が止まりました|応答がありません/.test(target.textContent)) {
          stalls.push(target.textContent);
        }
        if (/中断を検出しました/.test(target.textContent)) resumed.push(1);
      }).observe(target, { childList: true, characterData: true, subtree: true });
      const run = offSaveAll(PF_DEPTHS[0].id, btns[0]);
      // A worker that never answers means the save never returns - which is
      // precisely the state the watchdog exists for, so it cannot be awaited.
      if (mode === 'mute') await new Promise((r) => setTimeout(r, 9000));
      else await run;
      const c = await caches.open('gto-v2');
      return {
        stalls: stalls.length,
        resumed: resumed.length,
        stored: (await c.keys()).length,
        // Only the data files. The shell and the indexes are stored too, and a
        // PC serving no data at all still answers those - so counting
        // everything says "5 stored" about a run in which nothing arrived.
        dataStored: (await c.keys()).filter((k) => /\.json\.gz$/.test(k.url)).length,
        state: document.getElementById('off-state').textContent,
        note: document.getElementById('off-note').textContent,
        build: document.getElementById('off-build').textContent,
      };
    }, MODE);
    console.log(`        state: "${saved.state}"`);
    console.log(`        note:  "${saved.note}"`);
    console.log(`        build: "${saved.build}"`);
    // Which worker is running, said out loud on the device.
    //
    // The reason this exists: a phone can run a new index.html against an old
    // sw.js, and every symptom of that reads as the new code not working. The
    // panel has to be able to tell those two apart without a PC to check from,
    // so the same panel must name the current build AND call out an old one.
    if (NEW) {
      ok('the panel names the worker build it is running',
        /アプリ本体: \d{4}-\d{2}-\d{2}/.test(saved.build), saved.build);
    } else {
      ok('and says so when the worker is an old one',
        /古いバージョン/.test(saved.build), saved.build);
    }
    if (MODE === 'ok') {
      ok('the save stores every file', saved.stored > NFILES, JSON.stringify(saved));
      // The wording differs by worker: only the current one reports bytes, so
      // only it can print "n / n saved". The old one falls back to the storage
      // estimate. What must hold for both is that a clean save never mentions
      // a failure and never sits at a frozen zero.
      ok('and the headline reports a clean save',
        !/失敗/.test(saved.state) && !/^0 \//.test(saved.state), saved.state);
      // The reason the save was slow. One file at a time meant the link sat
      // idle for a round trip once per file, 299 times.
      if (NEW) {
        ok('and fetches several files at once rather than one at a time',
          maxInFlight > 1, `max ${maxInFlight} in flight`);
        console.log(`        max in flight: ${maxInFlight}`);
      } else {
        ok('the old worker fetched strictly one at a time',
          maxInFlight === 1, `max ${maxInFlight} in flight`);
      }
    } else if (MODE === 'fail') {
      // The case that read as a frozen zero. It has to name itself now.
      // The headline must not read as success while the data all failed. This
      // comes from the page, so it holds whichever worker is running.
      ok('a save where the data all fails does not claim success',
        /失敗 12/.test(saved.state) && !/保存済み/.test(saved.state), saved.state);
      // The cause comes from the worker, so only the current one can give it.
      if (NEW) {
        ok('and gives the reason rather than a guess',
          /HTTP 500/.test(saved.note), saved.note);
      } else {
        console.log('        (the old worker sends no reason - nothing to check)');
      }
    } else if (MODE === 'crash') {
      // The state that reached the user as a blank panel. A fault in the save
      // has to arrive on screen as the fault, not as nothing.
      ok('a crash inside the save is reported rather than swallowed',
        /エラー/.test(saved.state), saved.state);
      ok('and the panel shows what actually went wrong',
        /injected crash/.test(saved.note), saved.note);
    } else if (MODE === 'mute') {
      // The other way a save can produce nothing: the worker never answers at
      // all. The page must stop waiting and say so.
      ok('a worker that never answers is reported, not waited on for ever',
        /応答がありません/.test(saved.state), saved.state);
      ok('and the panel says what to do about it',
        /アプリを更新/.test(saved.note), saved.note);
      // The free-space figure is what tells the phone's own storage apart from
      // a PC that has gone quiet, and it is the number the user is asked to
      // read back - so it has to actually reach the screen.
      ok('and it reports the space left on the device, not only the fault',
        /端末の空き/.test(saved.note), saved.note);
    } else if (MODE === 'strict') {
      // The whole point: the save must survive a server that cannot take the
      // parallelism, rather than turning it into failures on screen.
      ok('a server that refuses parallel requests still gets a complete save',
        saved.stored > NFILES, JSON.stringify({ stored: saved.stored, refused }));
      ok('and nothing is reported as failed',
        !/失敗/.test(saved.state), saved.state);
      ok('and the refusals really happened, so the test is testing something',
        refused > 0, `refused ${refused}`);
      console.log(`        refused: ${refused}`);
    } else if (MODE === 'die') {
      // A worker killed mid-save. The page used to hand this back to the user
      // as "close the app and open it again", which made them the retry loop.
      ok('a worker that dies mid-save is noticed and the save restarted',
        saved.resumed > 0, `the page never restarted it (${saved.resumed})`);
      ok('and the restart finishes the job rather than reporting a failure',
        /保存しました/.test(saved.state) && !/失敗/.test(saved.state), saved.state);
      // The point of resuming rather than starting over: what already arrived
      // is skipped, so each attempt gets further instead of repeating itself.
      ok('and every file ends up stored',
        saved.stored > NFILES, JSON.stringify({ stored: saved.stored }));
    } else if (MODE === 'dead') {
      // The run that mattered: nothing is arriving, and every attempt costs a
      // full header timeout. Working through all of them proves nothing the
      // fifth file had not already shown, and on a real list of three hundred
      // it is over two hours of a counter climbing towards a total it will
      // never reach - which reads as progress.
      // Five attempted out of twelve. On the real list it is five out of three
      // hundred, which is the whole point.
      ok('a save where nothing arrives stops instead of grinding through the list',
        /5 件が続けて失敗/.test(saved.note) && /残りは試していません/.test(saved.note),
        JSON.stringify({ state: saved.state, note: saved.note }));
      ok('and says it stopped rather than implying the rest are still coming',
        /中止しました/.test(saved.state), saved.state);
      ok('and gives the reason it stopped for',
        /PC sent nothing for/.test(saved.note), saved.note);
      ok('and points at the one button that can tell PC from file',
        /PCに繋がるか確認/.test(saved.note), saved.note);
      ok('and no data file was stored, since none arrived',
        saved.dataStored === 0, JSON.stringify({ dataStored: saved.dataStored }));
    } else if (MODE === 'slow') {
      // The complaint this answers: "応答が止まりました" on a save that was
      // working. A worker that is alive says so every five seconds, so the
      // panel can tell a slow save from a dead one - and only accuse the user
      // of the second.
      ok('a slow file does not get the save reported as stopped',
        saved.stalls === 0, `the panel cried stall ${saved.stalls} time(s)`);
      ok('and the slow file is stored like any other',
        saved.stored > NFILES, JSON.stringify({ stored: saved.stored }));
      ok('and the save still reports a clean finish',
        !/失敗/.test(saved.state), saved.state);
    } else if (MODE === 'hang') {
      ok('a hung file does not stop the rest',
        saved.stored > 2, JSON.stringify({ stored: saved.stored }));
      ok('and the counter moved past zero', !/^0 \//.test(saved.state), saved.state);
      // A server that never answers and a transfer that dies half way are
      // different faults on different machines. The panel has to say which,
      // because "no answer in 120s" sent us looking in the wrong place.
      ok('and a PC that never answered is named as exactly that',
        /PC sent nothing for/.test(saved.note), saved.note);
    } else {
      // The case the old timeout could not catch: headers arrive, so fetch()
      // resolves and the timer was cleared, and then the body never finishes.
      // Nothing was left watching it, so the save stopped there for good -
      // which on screen is a counter that stops at a number and stays.
      ok('a file that stalls part-way through does not stop the rest',
        saved.stored > 2, JSON.stringify({ stored: saved.stored }));
      ok('and the save finishes rather than hanging on it',
        /12/.test(saved.state) || /失敗/.test(saved.state), saved.state);
      // The other half of the same distinction: this one DID start arriving,
      // and how far it got is the evidence that separates the two.
      ok('and a transfer that died half way says how far it got',
        /stopped after \d+ kB/.test(saved.note), saved.note);
      ok('and is not confused with a PC that never answered',
        !/PC sent nothing/.test(saved.note), saved.note);
    }
  }

  ok('no uncaught errors on the page', errors.length === 0, errors.join(' | '));

  await browser.close();
  await new Promise((r) => server.close(r));
  fs.rmSync(ROOT, { recursive: true, force: true });
  console.log(`\n=== ${pass} passed, ${fail} failed ===`);
  process.exit(fail ? 1 : 0);
})();
