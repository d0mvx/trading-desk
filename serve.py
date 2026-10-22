#!/usr/bin/env python3
"""Token-gated static server for ~/.desk/dashboard ONLY (stdlib). Binds 127.0.0.1:8080 (cloudflared connects locally).
Serves files only under /<token>/... or with ?k=<token>; everything else -> 404. No listings, no dotfiles."""
import os, hmac, mimetypes, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
DESK = os.path.expanduser("~/.desk"); ROOT = os.path.realpath(f"{DESK}/dashboard")
TOKEN = open(f"{DESK}/dash_token").read().strip()
ALLOWED = {"index.html", "data.json", "apple-touch-icon.png"}

class H(BaseHTTPRequestHandler):
    server_version = "desk"; sys_version = ""
    def log_message(self, fmt, *a):
        with open(f"{DESK}/logs/http.log", "a") as f:
            # never log the token
            f.write("%s %s\n" % (self.log_date_time_string(), (fmt % a).replace(TOKEN, "<token>")))
    def _404(self):
        self.send_response(404); self.send_header("Content-Type", "text/plain"); self.send_header("Content-Length", "9")
        self.end_headers(); self.wfile.write(b"not found") if self.command != "HEAD" else None
    def do_HEAD(self): self.do_GET()
    def do_GET(self):
        u = urllib.parse.urlsplit(self.path); q = urllib.parse.parse_qs(u.query)
        parts = [p for p in u.path.split("/") if p]
        ok = False; rel = None
        if parts and hmac.compare_digest(parts[0], TOKEN):
            ok, rel = True, "/".join(parts[1:]) or "index.html"
        elif hmac.compare_digest((q.get("k") or [""])[0], TOKEN):
            ok, rel = True, "/".join(parts) or "index.html"
        if not ok or rel not in ALLOWED: return self._404()
        if parts and parts[0] == TOKEN and len(parts) == 1 and not u.path.endswith("/"):
            self.send_response(301); self.send_header("Location", f"/{TOKEN}/"); self.end_headers(); return
        path = os.path.realpath(os.path.join(ROOT, rel))
        if not path.startswith(ROOT + os.sep) or not os.path.isfile(path): return self._404()
        body = open(path, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", (mimetypes.guess_type(path)[0] or "application/octet-stream") + ("; charset=utf-8" if rel.endswith((".html", ".json")) else ""))
        self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store")
        self.send_header("X-Robots-Tag", "noindex"); self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        if self.command != "HEAD": self.wfile.write(body)

if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8080), H).serve_forever()
