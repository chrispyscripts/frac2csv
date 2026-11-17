#!/usr/bin/env python3
"""Static server for web/public that answers HTTP Range requests.

Python's own http.server does not: it ignores Range and replies 200 with the
whole file.  pmtiles.js treats that as a hard error ("Check that your storage
backend supports HTTP Byte Serving") and every tile fails, so the survey grid
cannot be checked locally without this.  Vercel serves static files with range
support already, so this is a local-verification tool only.

  python3 serve.py [PORT] [--mount /data/sk=~/dev/fracview-sk ...]

--mount serves a folder outside public/ under a URL prefix: the Saskatchewan
set (build_sk.py) lives outside the repo, so it can only be seen this way.
"""
import http.server, os, re, socketserver, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "public")


MOUNTS = []          # (url prefix, folder), longest prefix first


class RangeHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=os.path.abspath(ROOT), **kw)

    def translate_path(self, path):
        clean = path.split("?", 1)[0].split("#", 1)[0]
        for prefix, folder in MOUNTS:
            if clean == prefix or clean.startswith(prefix + "/"):
                rest = clean[len(prefix):].lstrip("/")
                full = os.path.abspath(os.path.join(folder, *[p for p in rest.split("/") if p not in ("", ".", "..")]))
                return full if full.startswith(folder) else folder
        return super().translate_path(path)

    def end_headers(self):
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_head(self):
        rng = self.headers.get("Range")
        if not rng:
            return super().send_head()
        path = self.translate_path(self.path)
        if os.path.isdir(path) or not os.path.exists(path):
            return super().send_head()
        m = re.match(r"bytes=(\d*)-(\d*)$", rng.strip())
        if not m:
            return super().send_head()
        size = os.path.getsize(path)
        first, last = m.group(1), m.group(2)
        if first == "":                       # suffix range: last N bytes
            length = min(int(last or 0), size)
            start, end = size - length, size - 1
        else:
            start = int(first)
            end = int(last) if last else size - 1
        if start >= size or start > end:
            self.send_response(416)
            self.send_header("Content-Range", "bytes */%d" % size)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        end = min(end, size - 1)
        f = open(path, "rb")
        f.seek(start)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        self.remaining = end - start + 1
        return f

    def copyfile(self, source, outputfile):
        left = getattr(self, "remaining", None)
        if left is None:
            return super().copyfile(source, outputfile)
        self.remaining = None
        while left > 0:
            chunk = source.read(min(64 * 1024, left))
            if not chunk:
                break
            outputfile.write(chunk)
            left -= len(chunk)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    args, port = sys.argv[1:], int(os.environ.get("PORT", 8791))
    while args:
        a = args.pop(0)
        if a == "--mount" and args:
            prefix, folder = args.pop(0).split("=", 1)
            MOUNTS.append(("/" + prefix.strip("/"), os.path.abspath(os.path.expanduser(folder))))
        elif a.isdigit():
            port = int(a)
    MOUNTS.sort(key=lambda m: -len(m[0]))
    with Server(("127.0.0.1", port), RangeHandler) as httpd:
        print("serving %s on http://127.0.0.1:%d (Range supported)" % (os.path.abspath(ROOT), port))
        for prefix, folder in MOUNTS:
            print("  %s/ -> %s" % (prefix, folder))
        httpd.serve_forever()
