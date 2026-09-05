/* Makes the app work with the PC switched off.

   The phone keeps its own copy of everything - the page and every postflop
   file - in the Cache Storage the browser gives this origin. Once that copy
   exists nothing is fetched over the network again, so the PC it originally
   came from can be off, asleep, or on the other side of the world.

   The data files are cache-first. They never change underneath a given file
   name (a re-convert rewrites them wholesale, and the app asks for a new cache
   version then), so going to the network first would only add a timeout to
   every single request on a phone with no route to the PC - which is the
   normal case this exists for.

   The page itself is not. It was, and that made a new build unable to reach a
   device that had ever run this worker: index.html sat in the cache, the cache
   was consulted first, and the only ways out were bumping the cache version or
   clearing the copy - both of which throw away the hundreds of megabytes of
   data that have nothing to do with the page having changed. So the shell is
   network-first with a short timeout and the cached copy behind it, in
   exchange for a build being able to land. Everything the offline copy exists
   for still works with the PC off - the timeout expires and the cached page
   opens.

   What that launch request must NOT be is a download of the page. index.html
   is megabytes; asking for it outright to find out whether it changed spends
   the whole link on an answer that is almost always "it did not", and over a
   phone link it cannot finish inside any timeout short enough to launch on -
   so it was thrown away every time AND a genuinely new build could never land
   through it. It is a conditional request instead - If-Modified-Since, built
   from the copy already in Cache Storage - which asks the question and takes a
   304 for an answer. Cheap enough to fit in the timeout, which is what makes
   both halves work.

   Bumping CACHE_VERSION is how a re-converted dataset gets picked up: the new
   worker deletes every older cache on activate, so a stale mixture of old and
   new files cannot survive. v2 is the move to postflop/<depth>/<file>: the
   file names themselves changed, so anything cached under v1 points at paths
   that no longer exist. That matters more than it looks - a postflop file
   and the index.json that names it have to agree, and half-updating them would
   point the app at files that are no longer there. Note that a new PAGE is not
   a reason to bump it, and now does not need to be.
*/

const CACHE_VERSION = 'gto-v2';
/* Which build of this file the device is actually running.

   A worker updates on its own schedule and completely separately from the
   page, so a phone can be running a new index.html against a worker from two
   builds ago - and every symptom of that looks like a bug in the new code
   rather than like an old worker. There was no way to tell the two apart from
   the device, which is why this exists: the offline panel asks for it and
   prints it. Bump it whenever this file changes in a way worth telling apart.

   Not derived from CACHE_VERSION: bumping that throws away the stored data,
   which is exactly what must NOT happen just because the worker changed. */
const SW_BUILD = '2026-09-05b heartbeat';
/* './' is deliberately not here even though it is a real, reachable URL.
   The server answers it with index.html, so listing it stored the same
   megabytes twice and, far worse, downloaded them twice on every install -
   which is most of what made pressing "update" take minutes. A navigation to
   './' is served from './index.html' by the fetch handler below, so nothing
   is lost by not holding a second copy under a second name. */
const SHELL = ['./index.html', './manifest.webmanifest'];
// How long the page is allowed to wait for the PC before the stored copy is
// used instead. Long enough for a slow home network, short enough that opening
// the app away from the PC does not feel broken.
const SHELL_TIMEOUT_MS = 2500;
// The same question asked during an install, where the user has pressed
// "update" and is waiting, so it is worth waiting out a page that really did
// change. Bounded because an install that never finishes never activates the
// worker it was installing - see the note where this is used.
const INSTALL_TIMEOUT_MS = 180000;
/* Three deadlines, not one, because a file can fail to arrive in three
   different ways and they have three different causes.

   A single "no answer in 120s" could not tell them apart, and they are not
   variations of one problem: a server that never starts answering is a busy or
   stuck PC, a transfer that stops dead part-way is the link, and a transfer
   that is merely slow is neither and must not be cut off at all. The old
   single deadline said the same thing about all three and cut off the third.

   HEADER: the PC has this long to begin answering at all. A static file server
   that has not said a word in half a minute is not thinking about it - it is
   blocked on something.

   STALL: once bytes are flowing, this long with NO byte arriving ends it. This
   is what replaces a total deadline: a slow file is left alone for as long as
   it keeps making progress, and a dead one is given up on quickly.

   TOTAL: a backstop, so a file that dribbles a byte a second for ever still
   ends. Deliberately generous - it should never be what fires. */
const HEADER_TIMEOUT_MS = 30000;
const STALL_TIMEOUT_MS = 30000;
const FETCH_TIMEOUT_MS = 600000;
// The MOST files of an offline save that may be in flight at once - not the
// number it starts with. See the ramp in the save itself: it begins at one and
// only widens once files are actually arriving.
//
// One at a time was the whole reason a save of 299 files took so long that it
// looked broken. Each file costs a round trip before a single byte arrives, and
// over a phone link that latency is most of the time spent - so the link sat
// idle between files, once per file, 299 times. Fetching several at once fills
// that gap with the next file's transfer.
//
// Four, not more: a browser opens at most six connections to one host, and the
// page still has to be able to fetch anything it needs while a save runs. Above
// that the files start competing with each other instead of with the idle time.
const SAVE_CONCURRENCY = 4;
// How many files have to arrive in a row before another one is added to the
// number in flight.
const SAVE_RAMP_AFTER = 3;
// How many further goes a file gets before it counts as failed.
//
// A file that failed once is not a file that cannot be fetched. On a mobile
// link a dropped request is ordinary, and a small PC web server asked for four
// files at once may simply refuse the fourth. Either way the answer is the
// same and it is not "give up on that file": try it again, on its own.
const SAVE_RETRIES = 2;

/* Is this request for the page, rather than for data? Navigations count
   whatever they are spelled as, since that is the request that decides which
   build the user is looking at. */
function isShell(req, url) {
  if (req.mode === 'navigate') return true;
  const p = url.pathname;
  return p.endsWith('/') || p.endsWith('/index.html') || p.endsWith('/manifest.webmanifest');
}

/* The dataset manifest and the per-depth index.

   These are the only way the app can find out that a conversion has happened,
   so they cannot be cache-first: with them pinned, a re-converted dataset was
   unreachable on any device that had ever loaded the old one, and the only
   symptom was data that quietly never changed. That is how a full re-convert
   with blocker scores in it reached the app as an empty tab.

   Cheap to treat this way - two small JSON files per launch against hundreds
   of megabytes that stay cache-first. */
function isIndex(url) {
  return /\/postflop\/(?:[^/]+\/)?index\.json$/.test(url.pathname);
}

/* Everything belonging to one depth, but not its index.

   `dir` is the depth's folder ('40'), or '' for the pre-depth layout where the
   files sit directly in postflop/ - which is why this checks the remaining
   path rather than just a prefix: with dir '' a prefix test would match every
   depth's files and empty the whole cache. */
function inDepth(pathname, dir) {
  const at = pathname.indexOf('/postflop/');
  if (at < 0) return false;
  const rest = pathname.slice(at + '/postflop/'.length);
  if (rest.endsWith('index.json')) return false;
  return dir ? rest.startsWith(dir + '/') : !rest.includes('/');
}

self.addEventListener('install', (event) => {
  // The shell only. The postflop files are hundreds of megabytes and are
  // fetched deliberately from the app's offline panel, not silently on first
  // visit - half a gigabyte should never start downloading because someone
  // opened a page.
  //
  // One at a time and each allowed to fail, rather than addAll: addAll is all
  // or nothing, so installing while the PC is unreachable threw away a shell
  // that was already stored and perfectly good.
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_VERSION);
    for (const url of SHELL) {
      try {
        // A far longer deadline than a page load gets, because this runs
        // because the user pressed "update" and is waiting for one - but a
        // deadline all the same. It was Infinity, and that was a way to hang
        // for ever: nothing below this line runs until the fetch settles, so a
        // PC that never answers meant skipWaiting() was never reached, the new
        // worker never activated, and the app went on running the old one with
        // no sign that anything had gone wrong.
        //
        // Revalidating rather than downloading, for the same reason as the
        // fetch handler: an update that changes only this worker - which is
        // most of them - then costs a 304 per shell file instead of the whole
        // page again. Only a page that really did change is paid for, and that
        // is the difference between pressing "update" and waiting a moment
        // versus waiting out two full downloads of the page.
        const res = await fetchFresh(url, INSTALL_TIMEOUT_MS, await cache.match(url));
        if (res && res !== NOT_MODIFIED && res.status === 200) {
          await cache.put(url, res.clone());
        }
      } catch (e) { /* offline: keep whatever copy is already stored */ }
    }
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k)),
      ))
      .then(() => self.clients.claim()),
  );
});

/* Ask the PC for a file, and really stop asking at the deadline.

   Resolves to the response, or to null if it fails or takes too long. Null
   rather than a rejection because every caller here has the same answer to
   both - use the stored copy - and a promise that can reject would put a
   try/catch around the one line that decides which build gets shown.

   The abort is the point. This was a plain race between the fetch and a timer,
   which stopped the *waiting* at the deadline but left the request itself
   running to completion in the background. For a megabytes-long index.html
   over a phone link that is minutes of the link spent on a response nobody
   will ever look at, once per page load, against a browser limit of six
   connections to the host and a small single-machine web server behind it -
   so the offline save was left contending with the launch of the very page
   that started it. A timeout that does not cancel is not a timeout. */
const NOT_MODIFIED = Symbol('not-modified');

function fetchFresh(url, ms, stored) {
  const ctl = new AbortController();
  // Infinity for the install, which is a wait the user asked for; a real
  // deadline for a page load, which is not.
  const timer = Number.isFinite(ms) ? setTimeout(() => ctl.abort(), ms) : null;
  // The conditional request is built here, from the copy in Cache Storage,
  // rather than left to the browser's own cache via `cache: 'no-cache'`.
  //
  // That was the first attempt and it did nothing: the browser never had a
  // stored copy to revalidate against, so it sent no If-Modified-Since and the
  // server had no choice but to send the whole page. A 7 MB response is not
  // something an HTTP cache can be relied on to keep - there are per-entry size
  // limits, and they are neither documented nor ours to set. Cache Storage, on
  // the other hand, is the copy this worker put there on purpose and can count
  // on. Asking from there turns "has the page changed?" into a question we know
  // will be asked properly, on any browser, at any page size.
  const headers = {};
  const since = stored && stored.headers.get('last-modified');
  if (since) headers['if-modified-since'] = since;
  return fetch(new Request(url, {
    headers, cache: 'no-store', credentials: 'same-origin', signal: ctl.signal,
  })).then((res) => (res && res.status === 304 ? NOT_MODIFIED : res))
    .catch(() => null)
    .then((res) => { clearTimeout(timer); return res; });
}

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  event.respondWith((async () => {
    const cache = await caches.open(CACHE_VERSION);

    // The page: ask the PC first, briefly, so a rebuilt index.html is picked up
    // without discarding the data cache. Anything that goes wrong - the PC is
    // off, the network is slow, the server answers with an error - falls
    // through to the stored copy, which is the whole point of the worker.
    if (isShell(req, url)) {
      // fetchFresh builds a fresh Request from the URL, NOT fetch(req, init).
      // Passing an init alongside a navigation request throws outright -
      // "Cannot construct a Request with a RequestInit whose mode member is set
      // as 'navigate'" - and the throw is indistinguishable from the PC being
      // off, so every page load fell straight back to the stored copy. That is
      // the exact request this branch exists for, so the bug hid the whole
      // feature while a page-level fetch of the same file looked fine.
      // One stored entry for the page, whatever URL it was asked for by.
      // './' and './index.html' are the same megabytes from this server, so
      // storing under the requested URL kept a second whole copy of the page
      // as soon as anyone opened the bare directory address - and counted it
      // as data the user had saved. The manifest is matched by isShell() too
      // and is a genuinely different file, so it keeps its own name.
      const isManifest = url.pathname.endsWith('/manifest.webmanifest');
      const key = isManifest ? req : './index.html';
      const stored = await cache.match(key, { ignoreSearch: true });
      const fresh = await fetchFresh(url.href, SHELL_TIMEOUT_MS, stored);
      // The PC says it is still the copy we hold. That is the usual answer, and
      // it now costs one small round trip instead of the whole page.
      if (fresh === NOT_MODIFIED && stored) return stored;
      if (fresh && fresh !== NOT_MODIFIED && fresh.status === 200 && fresh.type === 'basic') {
        cache.put(key, fresh.clone());
        return fresh;
      }
      if (stored) return stored;
      // Nothing stored and nothing fetched: let the real request decide what
      // the failure looks like rather than inventing one.
      return fetch(req);
    }

    // The indexes: the same network-first treatment as the shell, and for the
    // same reason. They are small, and they are what tells the app a
    // conversion is newer than the copy it holds.
    if (isIndex(url)) {
      const stored = await cache.match(req, { ignoreSearch: true });
      const fresh = await fetchFresh(url.href, SHELL_TIMEOUT_MS, stored);
      if (fresh === NOT_MODIFIED && stored) return stored;
      if (fresh && fresh !== NOT_MODIFIED && fresh.status === 200 && fresh.type === 'basic') {
        cache.put(req, fresh.clone());
        return fresh;
      }
      if (stored) return stored;
      return fetch(req);
    }

    const hit = await cache.match(req, { ignoreSearch: true });
    if (hit) return hit;
    try {
      const res = await fetch(req);
      // Only store complete, successful responses. A 206 or an opaque error
      // page cached here would be indistinguishable from real data later, and
      // the failure would surface mid-hand as a file that will not gunzip.
      if (res && res.status === 200 && res.type === 'basic') {
        cache.put(req, res.clone());
      }
      return res;
    } catch (e) {
      // Offline and not cached. Navigations fall back to the shell so the app
      // still opens; anything else has to fail, and the app already treats a
      // missing postflop file as "no data past here".
      if (req.mode === 'navigate') {
        const shell = await cache.match('./index.html');
        if (shell) return shell;
      }
      throw e;
    }
  })());
});

/* The offline panel talks to the worker through these, rather than opening the
   cache itself, so there is exactly one place that decides which cache name is
   current. */
self.addEventListener('message', (event) => {
  const msg = event.data || {};
  if (msg.type === 'CACHE_URLS') {
    // Say something immediately, before anything that can fail.
    //
    // A save that produced no message at all was indistinguishable from a save
    // that was never asked for - and the panel had nothing to show either way,
    // so a fault anywhere below this line reached the user as a completely
    // blank screen. This one message proves the worker heard the request; if
    // it arrives and nothing follows, the fault is in the save, and if it does
    // not arrive the fault is in reaching the worker at all. Two different
    // problems that used to look the same.
    try {
      if (msg.port) {
        msg.port.postMessage({
          phase: 'accepted', done: 0, failed: 0, pending: 0,
          total: (msg.urls || []).length, bytes: 0, build: SW_BUILD,
        });
      }
    } catch (e) { /* the port is gone; the save below will find out too */ }
    event.waitUntil((async () => {
      // Between "accepted" and the first file there was one step and no word
      // about it, so a save that got stuck there looked exactly like a worker
      // that had died - and the panel's advice for that, close the app and
      // start again, is the one thing that cannot help. Opening the cache is
      // not free on a device holding hundreds of megabytes, so the step that
      // happens before anything else has to say that it is happening.
      const tell = (extra) => {
        try {
          if (msg.port) {
            msg.port.postMessage({
              done: 0, failed: 0, pending: 0, bytes: 0, build: SW_BUILD,
              total: (msg.urls || []).length, ...extra,
            });
          }
        } catch (e) { /* the port is gone; the save below will find out too */ }
      };
      tell({ phase: 'opening' });
      const cache = await caches.open(CACHE_VERSION);
      tell({ phase: 'opened' });
      let done = 0;
      let failed = 0;
      let bytes = 0;
      let firstError = null;
      const urls = msg.urls || [];
      const total = urls.length;
      let active = 0;
      // Every item, not every fifth.
      //
      // The panel showed "0 / 299" and sat there. Two different things look
      // like that and the screen could not tell them apart: a first file still
      // downloading (these are megabytes each, and five had to finish before
      // anything moved), and every single file failing (the counter reported
      // `done`, so a run where nothing succeeded counted up to nothing). Both
      // read as a frozen zero.
      let pending = 0;     // failed once, waiting for another go
      // Start at one, exactly as the version that was known to work did, and
      // widen only after files have actually been arriving. Starting at four
      // and coming down on failure was the wrong way round: it bet the first
      // four files on an assumption about the link and the PC's web server
      // that nothing had tested, and when the bet was wrong it was wrong from
      // the very first file.
      let limit = 1;
      let streak = 0;
      let lastReason = null;
      const say = (extra) => {
        if (msg.port) {
          msg.port.postMessage({
            done, failed, pending, total, bytes, firstError, lastReason, active, limit, ...extra,
          });
        }
      };

      // One file. Never throws, and never counts anything: it returns null when
      // the file is stored and a string saying why when it is not, so the
      // caller can decide whether that is a failure or just a first attempt.
      const fetchOne = async (url) => {
        // Declared out here so the catch below can read them. How far the file
        // got IS the diagnosis, and it would be out of scope anywhere inside.
        let started = false;      // have any bytes of the body arrived?
        let got = 0;
        try {
          // Skip what is already there: re-downloading half a gigabyte because
          // the panel was opened twice would be a poor way to treat a phone's
          // data allowance.
          if (await cache.match(url, { ignoreSearch: true })) return null;
          // Read the body a chunk at a time rather than handing the whole
          // response to cache.put().
          //
          // cache.put() is tidier and uses less memory, but it consumes the
          // body opaquely: when it fails there is no way to say whether the
          // file never started or stopped half way, and those are different
          // faults with different fixes. Reading it here costs one file held in
          // memory - a couple of megabytes, less than the two full copies this
          // held before any of this - and buys an answer to the only question
          // worth asking about a failed download.
          const ctl = new AbortController();
          let lastByte = Date.now();
          const hard = setTimeout(() => ctl.abort(), FETCH_TIMEOUT_MS);
          const guard = setInterval(() => {
            const quiet = Date.now() - lastByte;
            if (quiet > (started ? STALL_TIMEOUT_MS : HEADER_TIMEOUT_MS)) ctl.abort();
          }, 1000);
          try {
            const res = await fetch(url, { cache: 'no-store', signal: ctl.signal });
            if (!res || res.status !== 200) return `HTTP ${res ? res.status : '?'}`;
            lastByte = Date.now();
            const type = res.headers.get('content-type') || 'application/octet-stream';
            let body;
            if (res.body && res.body.getReader) {
              const reader = res.body.getReader();
              const chunks = [];
              for (;;) {
                const step = await reader.read();
                if (step.done) break;
                chunks.push(step.value);
                got += step.value.byteLength;
                started = true;
                lastByte = Date.now();
              }
              body = new Blob(chunks);
            } else {
              // No streaming body available. Rare, and the whole-response read
              // still works - it just cannot say how far it got.
              body = await res.arrayBuffer();
              got = body.byteLength;
              started = got > 0;
            }
            // Only the content type is carried over. Copying the response's
            // headers wholesale would carry Content-Encoding with them, and a
            // stored response claiming to be gzipped would be decoded a second
            // time on the way out - turning the .json.gz the app gunzips itself
            // into something that will not gunzip at all.
            await cache.put(url, new Response(body, { headers: { 'content-type': type } }));
            bytes += got;
            return null;
          } finally { clearTimeout(hard); clearInterval(guard); }
        } catch (e) {
          // The reason, returned rather than swallowed - and specific enough to
          // act on. "no answer in 120s" was true of three different faults.
          if (e && e.name === 'AbortError') {
            if (!started) return `PC sent nothing for ${HEADER_TIMEOUT_MS / 1000}s`;
            return `stopped after ${Math.round(got / 1024)} kB`;
          }
          return (e && e.message) || String(e);
        }
      };

      // A pulse for as long as this is alive, so that silence means one thing
      // instead of two. A save that is merely slow - one big file on a slow
      // link, which is normal here - looked identical to a worker that had been
      // killed, and the panel accused the user of the second whenever it saw
      // the first. Anything arriving resets the page's watchdog, so with this
      // running, a stalled panel really does mean a stopped worker.
      const beat = setInterval(() => say({ phase: 'alive' }), 5000);
      // Everything from here can throw, and a throw inside waitUntil goes
      // nowhere: the page is left waiting on a promise that will never settle,
      // with an empty panel and no clue. Whatever happens, the save reports an
      // ending.
      try {
      // First pass: several at once. See SAVE_CONCURRENCY - one at a time spent
      // most of the save waiting for the next round trip rather than
      // transferring.
      //
      // With a ceiling that comes down when files start failing. Fetching four
      // at once is an assumption about what the link and the PC's web server
      // will take, and a small server handed four requests at once may well
      // answer three of them; there is no way to know that from here in
      // advance. So the assumption is tested rather than trusted: every failure
      // retires one of the workers, and a save that cannot take any parallelism
      // at all walks itself down to one at a time and keeps going.
      let next = 0;
      const retry = [];
      const pump = async (id) => {
        while (next < urls.length) {
          // Above the current width: wait rather than exit, so this worker can
          // join in if the save earns its way up to a wider one later.
          if (id >= limit) {
            await new Promise((r) => setTimeout(r, 400));
            continue;
          }
          const url = urls[next++];
          active++;
          say({ url, phase: 'start' });
          const why = await fetchOne(url);
          active--;
          if (why) {
            // Not `failed` yet - it gets another go alone at the end. It is
            // still counted in the progress through `pending`, so the panel
            // keeps moving even in a run where nothing is succeeding.
            retry.push(url);
            pending++;
            lastReason = `${url}: ${why}`;
            // All the way back to one, not down by one. Whatever went wrong,
            // the one width that has been shown to work on this device is one.
            limit = 1;
            streak = 0;
          } else {
            done++;
            streak++;
            if (streak >= SAVE_RAMP_AFTER && limit < SAVE_CONCURRENCY) {
              limit++;
              streak = 0;
            }
          }
          say({ url });
        }
      };
      await Promise.all(Array.from({ length: Math.min(SAVE_CONCURRENCY, total) },
        (_, i) => pump(i)));

      // Second pass: what failed, one at a time, with a pause between goes.
      // Nothing else is in flight here, so a file that fails now failed on its
      // own terms rather than because of what was running beside it.
      for (const url of retry) {
        let why = null;
        for (let attempt = 0; attempt <= SAVE_RETRIES; attempt++) {
          if (attempt) await new Promise((r) => setTimeout(r, 800 * attempt));
          say({ url, phase: 'retry', attempt: attempt + 1 });
          why = await fetchOne(url);
          if (!why) break;
        }
        pending--;
        if (why) {
          failed++;
          if (!firstError) firstError = `${url}: ${why}`;
        } else done++;
        say({ url, phase: 'retry' });
      }
      say({ finished: true });
      } catch (e) {
        // Named, so the panel can print it. A save that ends this way has a
        // bug behind it, and the message is the only way it will ever be seen
        // - there is no console on the phone this runs on.
        say({ finished: true, fatal: (e && (e.stack || e.message)) || String(e) });
      } finally {
        clearInterval(beat);
      }
    })());
  } else if (msg.type === 'DROP_DEPTH') {
    // One depth's data files, thrown away because the app noticed the manifest
    // now says they were converted at a different time. Scoped to the depth so
    // re-converting 40BB does not cost the phone the 20BB download it still
    // has - which is what bumping CACHE_VERSION would have done, and is why
    // bumping it was never a workable answer to "the data changed".
    event.waitUntil((async () => {
      const cache = await caches.open(CACHE_VERSION);
      const keys = await cache.keys();
      let dropped = 0;
      for (const k of keys) {
        let p;
        try { p = new URL(k.url).pathname; } catch (e) { continue; }
        if (!inDepth(p, msg.dir || '')) continue;
        if (await cache.delete(k)) dropped++;
      }
      // `finished` because that is what offAsk() in the page waits for; a
      // reply without it is read as progress and the caller never resolves.
      if (msg.port) msg.port.postMessage({ dropped, dir: msg.dir || '', finished: true });
    })());
  } else if (msg.type === 'SKIP_WAITING') {
    // Sent by the page's update button to a worker that has installed and is
    // waiting. install() already calls this, so it is normally redundant - but
    // it costs nothing and covers the case where the waiting worker got there
    // by some other route.
    self.skipWaiting();
  } else if (msg.type === 'PING') {
    // Which build is answering. An older worker has no handler for this and
    // simply says nothing, so the panel's timeout is itself the answer: no
    // reply means the device is not running this file.
    if (msg.port) msg.port.postMessage({ build: SW_BUILD, cache: CACHE_VERSION, finished: true });
  } else if (msg.type === 'CLEAR') {
    event.waitUntil((async () => {
      await caches.delete(CACHE_VERSION);
      if (msg.port) msg.port.postMessage({ cleared: true });
    })());
  }
});
