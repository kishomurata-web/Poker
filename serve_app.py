"""Serves this folder and opens the app in a browser.

Run it directly, or via run_app.bat.

    python serve_app.py             PC only (127.0.0.1)
    python serve_app.py --lan       also reachable from a phone on the same Wi-Fi
    python serve_app.py --tailscale reachable from your own devices anywhere

--tailscale binds to the Tailscale address *only*, not to every interface. That
is the difference that matters when this PC is ever on a network you do not
control: --lan would answer anyone on that network, while --tailscale answers
nothing but your own tailnet. Traffic over the tailnet is WireGuard-encrypted,
so plain http across it is not carried in the clear.

The browser is only launched after the socket is already listening. Launching
it first - which is what run_app.bat used to do - reliably produced "this page
can't be reached", because `start` returns immediately and the browser arrived
before the port was bound.
"""

import argparse
import errno
import functools
import json
import http.server
import os
import socket
import socketserver
import subprocess
import sys
import threading
import webbrowser

BASE = os.path.dirname(os.path.abspath(__file__))
FIRST_PORT = 8123
TRIES = 12


class Handler(http.server.SimpleHTTPRequestHandler):
    # Keep the connection open between files.
    #
    # SimpleHTTPRequestHandler speaks HTTP/1.0 by default, which means the
    # connection is torn down after every single response. For one page that is
    # invisible. For the offline save it is 299 separate TCP connections, each
    # paying a full round trip to the phone before a byte of the file moves -
    # and, through `tailscale serve`, a fresh proxied connection behind that
    # one too. With keep-alive the whole save runs over a handful of
    # connections that stay open.
    #
    # Safe here because every response this handler produces carries an
    # accurate Content-Length: files get one from the stat, directory listings
    # from the generated page, and errors from send_error. That is the only
    # thing HTTP/1.1 needs in order to know where one response ends.
    protocol_version = "HTTP/1.1"
    # A kept-open connection holds a thread, so a client that goes away without
    # saying so - a phone that walks out of range mid-save, which is the normal
    # case here - must not hold one for ever.
    #
    # This applies to every socket operation, WRITES INCLUDED, so it is also a
    # ceiling on how long one send may block while a slow phone drains it. Sixty
    # seconds was the first value here and it was too near the mark: a large
    # file to a phone on a mobile link can sit in a blocked write for a while
    # without anything being wrong, and hitting this cuts the transfer off
    # mid-file - a failure invented by the server rather than found by it. Five
    # minutes of a single write making no progress at all really is a dead
    # connection.
    timeout = 300

    def log_message(self, fmt, *args):
        # One line per request is noise; only surface problems.
        code = str(args[1]) if len(args) > 1 else ""
        if code and code[0] in "45":
            sys.stderr.write("  %s %s\n" % (code, args[0]))

    def guess_type(self, path):
        # The app fetches .json.gz and gunzips it itself, so these must arrive
        # as opaque bytes. Setting this in end_headers() instead would emit a
        # second Content-Type on top of the one already queued. What must never
        # appear is Content-Encoding: gzip - that makes the browser decompress
        # transparently, and the app would then try to gunzip plain JSON.
        if path.endswith(".gz"):
            return "application/octet-stream"
        return super().guess_type(path)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    # How many connections may be waiting to be accepted at once.
    #
    # socketserver's default is five. Five was fine while the only client was a
    # browser on this PC fetching one page. It is not fine when the phone's
    # offline save asks for several files at once: connections arriving while
    # those five are queued are refused outright by Windows, and on the phone a
    # refused connection is simply a file that failed. That is a failure caused
    # entirely by asking for more than one file at a time, which is exactly the
    # shape of the problem this had.
    #
    # Sixty-four costs nothing - it is a kernel queue length, not threads.
    request_queue_size = 64


def lan_address():
    """This machine's address on the local network.

    Opening a UDP socket towards a public address and reading back the local
    end is the portable way to ask "which interface would be used to leave this
    machine" - no packet is actually sent. Reading the hostname instead lands on
    127.0.0.1 on many Windows setups, which is exactly the answer that does not
    help here.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


TAILSCALE_EXES = [
    "tailscale",
    r"C:\Program Files\Tailscale\tailscale.exe",
    r"C:\Program Files (x86)\Tailscale\tailscale.exe",
    "/usr/bin/tailscale",
    "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
]


def _in_tailscale_range(ip):
    """Tailscale hands out addresses from 100.64.0.0/10 (the CGNAT range)."""
    parts = ip.split(".")
    if len(parts) != 4 or parts[0] != "100":
        return False
    try:
        return 64 <= int(parts[1]) <= 127
    except ValueError:
        return False


def tailscale_address():
    """(ipv4, dns_name) for this machine on the tailnet, or (None, None).

    Asks the tailscale CLI first because it also gives the MagicDNS name, which
    is far easier to type on a phone than 100.x.y.z. Falls back to scanning this
    host's own addresses for one in Tailscale's range, so a working setup is
    still found when the CLI is not where we looked.
    """
    for exe in TAILSCALE_EXES:
        try:
            ip = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True,
                                timeout=5).stdout.strip().splitlines()
        except (OSError, subprocess.SubprocessError):
            continue
        if not ip or not _in_tailscale_range(ip[0].strip()):
            continue
        name = None
        try:
            out = subprocess.run([exe, "status", "--json"], capture_output=True,
                                 text=True, timeout=5).stdout
            self_ = json.loads(out).get("Self") or {}
            name = (self_.get("DNSName") or "").rstrip(".") or None
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
        return ip[0].strip(), name

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if _in_tailscale_range(ip):
                return ip, None
    except OSError:
        pass
    return None, None


PID_FILE = os.path.join(BASE, "_server.pid")


def be_unobtrusive():
    """Drop this process below the collector in the scheduler's queue.

    Serving static files is close to free while nothing is being fetched - the
    process sits blocked in accept() - so this is not where a slow collection
    comes from. What did cost something was the browser the server opened on
    the PC every time it started, which is a real process and competes with the
    Chrome the collector drives over CDP. --background stops opening it.

    Below-normal rather than idle: idle-priority processes can be starved
    outright by a busy machine, and a server the phone is waiting on should
    yield, not stall. On anything but Windows this is a no-op, which is fine -
    the collection this defers to only runs there.
    """
    try:
        import ctypes
        BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        ctypes.windll.kernel32.SetPriorityClass(handle, BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        pass


def running_pid():
    """The pid in the file, if that process is actually alive.

    A pid file outlives a hard kill - taskkill, a power cut, Stop-Process - so
    its presence alone means nothing. Without this check a second launch would
    quietly bind the next port up, and with no window on screen there would be
    nothing to say which of the two the phone was talking to.
    """
    try:
        with open(PID_FILE, encoding="utf-8") as fh:
            pid = int(fh.read().strip())
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)          # signal 0: existence check, changes nothing
    except OSError:
        return None
    except Exception:
        return None
    return pid


def write_pid_file():
    """So stop_app_background.bat can stop exactly this, and nothing else.

    Killing "python running serve_app.py" by command line would be close
    enough most of the time, and would also be a way to shoot down an unrelated
    Python on a bad day. A pid written by the process itself is exact.
    """
    try:
        with open(PID_FILE, "w", encoding="utf-8") as fh:
            fh.write(str(os.getpid()))
    except OSError:
        pass


def clear_pid_file():
    try:
        os.remove(PID_FILE)
    except OSError:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lan", action="store_true",
                    help="listen on all interfaces so a phone on the same Wi-Fi can connect")
    ap.add_argument("--tailscale", action="store_true",
                    help="listen on the Tailscale address only, reachable from your devices anywhere")
    ap.add_argument("--no-browser", action="store_true", help="do not open a browser")
    ap.add_argument("--port", type=int, default=0,
                    help="use exactly this port and fail if it is taken, rather "
                         "than searching upwards from %d" % FIRST_PORT)
    ap.add_argument("--background", action="store_true",
                    help="run quietly out of the way: no browser, below-normal "
                         "priority, and a pid file so it can be stopped again")
    args = ap.parse_args()
    if args.background:
        args.no_browser = True
        alive = running_pid()
        if alive:
            print("Already running in the background (pid %d)." % alive)
            print("Stop it first with stop_app_background.bat, or just use it.")
            return 0
        clear_pid_file()          # stale from a hard kill; safe to drop
        be_unobtrusive()

    if not os.path.exists(os.path.join(BASE, "index.html")):
        print("index.html was not found next to this script:\n  %s" % BASE)
        print("Put serve_app.py in the same folder as index.html.")
        return 1

    handler = functools.partial(Handler, directory=BASE)
    ts_ip = ts_name = None
    if args.tailscale:
        ts_ip, ts_name = tailscale_address()
        if not ts_ip:
            print()
            print("  Tailscale does not look like it is running on this PC.")
            print()
            print("   1. Install it from https://tailscale.com/download/windows")
            print("   2. Sign in (the same account you use on the phone)")
            print("   3. Check the tray icon says Connected, then run this again")
            print()
            print("  To use it on this Wi-Fi only for now:  run_app_phone.bat")
            return 1
    host = ts_ip if ts_ip else ("0.0.0.0" if args.lan else "127.0.0.1")
    httpd = None
    port = None
    last = None
    # A fixed port matters when something else is pointed at it. `tailscale
    # serve` forwards to one address, so a server that quietly moved to the next
    # port up would leave the https name resolving to nothing - and the phone,
    # which is the whole audience here, would see only a connection error.
    ports = [args.port] if args.port else range(FIRST_PORT, FIRST_PORT + TRIES)
    for p in ports:
        try:
            httpd = Server((host, p), handler)
            port = p
            break
        except OSError as e:
            last = e
            # "This address is not one of mine" is a different problem from
            # "this port is taken", and retrying eleven more ports cannot fix
            # it. Reporting it as a port clash sends the user hunting for a
            # program that is not there.
            if e.errno in (errno.EADDRNOTAVAIL, getattr(errno, "WSAEADDRNOTAVAIL", -1)):
                break
            continue
    if httpd is None:
        if last is not None and last.errno in (errno.EADDRNOTAVAIL,
                                               getattr(errno, "WSAEADDRNOTAVAIL", -1)):
            print()
            print("  Could not listen on %s - this PC does not currently hold" % host)
            print("  that address.")
            if ts_ip:
                print()
                print("  Tailscale reported it, so it is most likely disconnected or")
                print("  still starting. Check the tray icon says Connected and run")
                print("  this again.")
            return 1
        if args.port:
            print("Port %d is already in use. Close whatever is using it, or "
                  "stop an older copy with stop_app_background.bat." % args.port)
        else:
            print("Ports %d-%d are all in use. Close any other copy of this window "
                  "and try again." % (FIRST_PORT, FIRST_PORT + TRIES - 1))
        return 1

    url = "http://%s:%d/index.html" % (ts_ip if ts_ip else "127.0.0.1", port)
    has_data = os.path.isdir(os.path.join(BASE, "postflop"))
    print()
    print("  Serving %s" % BASE)
    print("  %s" % url)
    if ts_ip:
        print()
        print("  " + "=" * 52)
        print("  On your phone (anywhere, with Tailscale connected):")
        print()
        if ts_name:
            print("      http://%s:%d" % (ts_name, port))
            print("      http://%s:%d      (if the name does not resolve)" % (ts_ip, port))
        else:
            print("      http://%s:%d" % (ts_ip, port))
        print()
        print("  " + "=" * 52)
        print()
        print("  Notes:")
        print("   - Only devices signed into your own Tailscale account can")
        print("     reach this. Nothing is published to the internet.")
        print("   - Do NOT turn on Tailscale Funnel: that would publish it.")
        if args.background:
            print("   - This PC must stay awake, but there is no window to keep open.")
        else:
            print("   - This PC must stay awake and this window must stay open.")
        print("   - Windows may ask to allow Python through the firewall.")
    elif args.lan:
        ip = lan_address()
        print()
        if ip:
            print("  " + "=" * 46)
            print("  On your phone (same Wi-Fi), open:")
            print()
            print("      http://%s:%d" % (ip, port))
            print()
            print("  " + "=" * 46)
        else:
            print("  Could not work out this PC's network address. Run `ipconfig`")
            print("  and use the IPv4 address of your Wi-Fi adapter, with :%d" % port)
        print()
        print("  Notes:")
        print("   - Windows will ask to allow Python through the firewall the")
        print("     first time. Allow it on PRIVATE networks only.")
        print("   - Anyone else on this network can reach the app while this")
        print("     window is open. Close it when you are done.")
        print("   - This PC must stay awake for the phone to keep working.")
    if not has_data:
        print()
        print("  NOTE: no 'postflop' folder here, so training will stop at the")
        print("        flop. Run:  python postflop_convert.py")
    print()
    if args.background:
        print("  Running in the background. Nothing to keep open.")
        print("  Stop it with stop_app_background.bat")
    else:
        print("  Leave this window open while you use the app.")
        print("  Press Ctrl+C to stop.")
    print()

    # The socket is bound and listening by now, so the browser cannot beat it.
    if not args.no_browser:
        threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()
    if args.background:
        write_pid_file()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
        if args.background:
            clear_pid_file()
    return 0


if __name__ == "__main__":
    sys.exit(main())
