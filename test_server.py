"""Can the PC's web server take what the phone's offline save asks of it?

    python test_server.py

The save fetches several files at once now. That is a different thing to ask of
a server than one browser fetching one page, and serve_app.py was configured -
by inheriting socketserver's defaults - for the second. This measures the
difference: the same requests against the settings as they were and as they are.

Nothing here needs a browser or a phone. It is the server on its own.
"""
import http.client
import io
import os
import shutil
import socketserver
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import serve_app  # noqa: E402

PASS = [0]
FAIL = [0]


def ok(name, cond, detail=""):
    if cond:
        PASS[0] += 1
        print("  PASS  " + name)
    else:
        FAIL[0] += 1
        print("  FAIL  " + name + (" - " + str(detail) if detail else ""))


# The file sizes are what makes this a fair test: a response small enough to sit
# in one packet never exercises the parts that go wrong under load.
NFILES = 24
FILE_BYTES = 400_000


def make_tree():
    root = tempfile.mkdtemp(prefix="srvtest-")
    with open(os.path.join(root, "index.html"), "w", encoding="utf-8") as fh:
        fh.write("<title>t</title>")
    blob = os.urandom(FILE_BYTES)
    for i in range(NFILES):
        with open(os.path.join(root, "f%02d.json.gz" % i), "wb") as fh:
            fh.write(blob)
    return root


class Counting:
    """Mixed into a server so the test can see how many connections it took.

    This is the number that says whether keep-alive is working: 24 files over
    four connections is keep-alive, 24 files over 24 connections is not.
    """

    def __init__(self, *a, **kw):
        self.conns = 0
        self.lock = threading.Lock()
        super().__init__(*a, **kw)

    def get_request(self):
        with self.lock:
            self.conns += 1
        return super().get_request()


def build(root, legacy):
    """A server with today's settings, or with the ones this had before."""
    if legacy:
        class LegacyHandler(serve_app.Handler):
            protocol_version = "HTTP/1.0"   # what SimpleHTTPRequestHandler gives you
            timeout = None

        class LegacyServer(Counting, socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True
            request_queue_size = 5          # socketserver's default

        handler, server_cls = LegacyHandler, LegacyServer
    else:
        class CurrentServer(Counting, serve_app.Server):
            pass

        handler, server_cls = serve_app.Handler, CurrentServer

    import functools
    httpd = server_cls(("127.0.0.1", 0), functools.partial(handler, directory=root))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd


def hammer(port, paths, threads):
    """Fetch every path, `threads` at a time, reusing connections where allowed.

    Reconnecting on failure rather than giving up, because that is what the
    service worker does too - a client that gave up on the first refusal would
    measure something no real client experiences.
    """
    errors = []
    got = []
    lock = threading.Lock()
    work = list(paths)
    idx = [0]

    def run():
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
        while True:
            with lock:
                if idx[0] >= len(work):
                    break
                p = work[idx[0]]
                idx[0] += 1
            last = None
            for attempt in range(3):
                try:
                    conn.request("GET", p)
                    r = conn.getresponse()
                    body = r.read()
                    if r.status != 200:
                        raise RuntimeError("HTTP %d" % r.status)
                    with lock:
                        got.append((p, len(body), r.getheader("Content-Type"),
                                    r.getheader("Content-Encoding")))
                    last = None
                    break
                except Exception as e:              # noqa: BLE001 - report anything
                    last = "%s: %s" % (type(e).__name__, e)
                    try:
                        conn.close()
                    except Exception:               # noqa: BLE001
                        pass
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
                    time.sleep(0.05 * (attempt + 1))
            if last:
                with lock:
                    errors.append("%s %s" % (p, last))
        try:
            conn.close()
        except Exception:                           # noqa: BLE001
            pass

    ts = [threading.Thread(target=run) for _ in range(threads)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return got, errors


def main():
    root = make_tree()
    paths = ["/f%02d.json.gz" % i for i in range(NFILES)]
    try:
        print()
        for legacy in (True, False):
            label = "before (HTTP/1.0, backlog 5)" if legacy else "now (HTTP/1.1, backlog 64)"
            httpd = build(root, legacy)
            port = httpd.server_address[1]
            started = time.time()
            got, errors = hammer(port, paths, threads=4)
            secs = time.time() - started
            conns = httpd.conns
            httpd.shutdown()
            httpd.server_close()
            print("  %s" % label)
            print("      %d files, %d connections, %.2fs, %d errors"
                  % (len(got), conns, secs, len(errors)))
            if errors:
                print("      first error: %s" % errors[0])

            if legacy:
                # The point of measuring the old settings: one connection per
                # file. Every one of those is a round trip to the phone before
                # any of the file moves.
                ok("before: a connection was set up for every single file",
                   conns >= NFILES, "%d connections for %d files" % (conns, NFILES))
            else:
                ok("every file arrives, with four requests in flight",
                   len(got) == NFILES and not errors,
                   "%d/%d, errors: %s" % (len(got), NFILES, errors[:1]))
                ok("and the files are whole",
                   all(n == FILE_BYTES for _, n, _, _ in got),
                   sorted({n for _, n, _, _ in got}))
                ok("and the connections are reused rather than rebuilt per file",
                   conns <= NFILES // 2, "%d connections for %d files" % (conns, NFILES))
                # The one thing that must not change: the app gunzips these
                # itself, so they have to arrive as opaque bytes.
                ok("and .gz still arrives undecoded, as the app requires",
                   all(ct == "application/octet-stream" and ce is None
                       for _, _, ct, ce in got),
                   sorted({(ct, ce) for _, _, ct, ce in got}))
            print()

        # A burst far wider than the save will ever produce, to show the queue
        # is no longer the thing that decides whether a file fails.
        httpd = build(root, legacy=False)
        port = httpd.server_address[1]
        got, errors = hammer(port, paths * 3, threads=16)
        conns = httpd.conns
        httpd.shutdown()
        httpd.server_close()
        print("  a burst of 16 at once: %d files, %d connections, %d errors"
              % (len(got), conns, len(errors)))
        ok("sixteen at once is served without a single failure",
           len(got) == NFILES * 3 and not errors,
           "%d/%d, errors: %s" % (len(got), NFILES * 3, errors[:1]))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n=== %d passed, %d failed ===" % (PASS[0], FAIL[0]))
    return 1 if FAIL[0] else 0


if __name__ == "__main__":
    sys.exit(main())
