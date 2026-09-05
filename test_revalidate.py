"""Does asking "has the page changed?" cost a round trip, or the whole page?

    python test_revalidate.py

The worker now revalidates the shell instead of downloading it: `cache:
'no-cache'`, which puts If-Modified-Since on the request and expects a 304 when
nothing has changed. That is the entire reason a page load no longer spends
megabytes of the phone's link on an answer that is almost always "no" - so it is
worth knowing for certain that this server actually answers that way, rather
than assuming it because SimpleHTTPRequestHandler is documented to.

The failure this guards against is quiet and expensive: a server that ignored
the header would answer 200 with the whole file every time, everything would
still work, and the only symptom would be the slowness we just spent a day
finding.
"""
import email.utils
import functools
import http.client
import os
import shutil
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


# Big enough that "did it send the body?" is unmistakable in the numbers, and
# roughly the shape of the real index.html, which is what this is about.
PAGE_BYTES = 2_000_000


def make_tree():
    root = tempfile.mkdtemp(prefix="revaltest-")
    with open(os.path.join(root, "index.html"), "w", encoding="utf-8") as fh:
        fh.write("<title>t</title>" + "x" * PAGE_BYTES)
    with open(os.path.join(root, "manifest.webmanifest"), "w", encoding="utf-8") as fh:
        fh.write('{"name":"t"}')
    with open(os.path.join(root, "f.json.gz"), "wb") as fh:
        fh.write(os.urandom(1000))
    return root


def serve(root):
    httpd = serve_app.Server(
        ("127.0.0.1", 0), functools.partial(serve_app.Handler, directory=root))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def get(port, path, ims=None):
    """(status, headers, body), with headers looked up case-insensitively.

    HTTP header names are case-insensitive and this server spells them
    "Content-type"; a plain dict of the pairs answers None to "Content-Type"
    and the test reads as a server that stopped setting it.
    """
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    try:
        headers = {"If-Modified-Since": ims} if ims else {}
        conn.request("GET", path, headers=headers)
        r = conn.getresponse()
        body = r.read()
        return r.status, r.headers, body
    finally:
        conn.close()


def main():
    root = make_tree()
    httpd = serve(root)
    port = httpd.server_address[1]
    try:
        print()
        # 1. A plain request has to carry the thing a revalidation is built on.
        status, headers, body = get(port, "/index.html")
        lastmod = headers.get("Last-Modified")
        ok("the page is served with a Last-Modified to revalidate against",
           status == 200 and lastmod, "status %s, Last-Modified %r" % (status, lastmod))
        ok("and the whole page arrives on a first, unconditional request",
           len(body) > PAGE_BYTES, len(body))

        # 2. The point of the exercise.
        status, headers, body = get(port, "/index.html", ims=lastmod)
        ok("asking again with If-Modified-Since answers 304, not the page",
           status == 304, "status %s" % status)
        ok("and sends no body at all - this is the megabytes that stop moving",
           len(body) == 0, "%d bytes" % len(body))

        # 3. A page that really did change must still get through, or the
        #    update button would have nothing to deliver.
        time.sleep(1.1)          # Last-Modified has one-second resolution
        with open(os.path.join(root, "index.html"), "w", encoding="utf-8") as fh:
            fh.write("<title>NEW</title>" + "y" * PAGE_BYTES)
        status, headers, body = get(port, "/index.html", ims=lastmod)
        ok("but a page that changed is sent in full, so an update can land",
           status == 200 and b"NEW" in body, "status %s" % status)

        # 4. The manifest is in SHELL too and goes down the same path.
        status, headers, _ = get(port, "/manifest.webmanifest")
        status2, _, body2 = get(port, "/manifest.webmanifest",
                                ims=headers.get("Last-Modified"))
        ok("the manifest revalidates the same way", status == 200 and status2 == 304,
           "%s then %s" % (status, status2))

        # 5. The one thing none of this may disturb: the app gunzips these
        #    itself, so they must keep arriving as opaque, undecoded bytes.
        status, headers, body = get(port, "/f.json.gz")
        ok("and .gz data files are untouched by any of this",
           status == 200 and headers.get("Content-Type") == "application/octet-stream"
           and headers.get("Content-Encoding") is None and len(body) == 1000,
           (status, headers.get("Content-Type"), headers.get("Content-Encoding"), len(body)))
    finally:
        httpd.shutdown()
        httpd.server_close()
        shutil.rmtree(root, ignore_errors=True)

    print("\n=== %d passed, %d failed ===" % (PASS[0], FAIL[0]))
    return 1 if FAIL[0] else 0


if __name__ == "__main__":
    sys.exit(main())
