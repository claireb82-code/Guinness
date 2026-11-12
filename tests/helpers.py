"""Shared test helpers: tiny local HTTP servers and a fake Upstash/Redis REST server."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class QuietHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep test output clean
        pass


def serve(handler_cls, host="127.0.0.1"):
    """Start ``handler_cls`` on an ephemeral port in a thread. Returns (server, base_url)."""
    server = ThreadingHTTPServer((host, 0), handler_cls)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.02), daemon=True)
    thread.start()
    return server, f"http://{host}:{server.server_address[1]}"


def stop(server):
    server.shutdown()
    server.server_close()


def page_server(routes, hits=None):
    """``routes``: path -> (status, headers dict, body bytes). Records requested paths in ``hits``."""

    class H(QuietHandler):
        def do_GET(self):
            if hits is not None:
                hits.append(self.path)
            status, headers, body = routes.get(self.path, (404, {}, b"not found"))
            self.send_response(status)
            headers = {"Content-Type": "text/html", **headers}
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return serve(H)


class FakeRedis:
    """In-memory model of the Redis commands storage.py uses, served via Upstash's REST protocol
    (POST /pipeline with a JSON list of commands). It models the documented API; it has NOT been
    verified against a real Upstash instance."""

    def __init__(self, token="test-token"):
        self.token = token
        self.data = {}  # key -> list | dict | str
        self.expiry = {}
        self.fail = False  # simulate an outage
        self.requests = 0
        self.server = None
        self.url = None
        outer = self

        class H(QuietHandler):
            def do_POST(self):
                outer.requests += 1
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                if self.headers.get("Authorization") != f"Bearer {outer.token}":
                    return self._send(401, {"error": "unauthorized"})
                if outer.fail:
                    return self._send(500, {"error": "boom"})
                if self.path != "/pipeline":
                    return self._send(404, {"error": "not found"})
                out = []
                for cmd in json.loads(body):
                    try:
                        out.append({"result": outer.run(cmd)})
                    except Exception as exc:  # noqa: BLE001
                        out.append({"error": f"ERR {exc}"})
                self._send(200, out)

            def _send(self, status, payload):
                raw = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self._H = H

    def start(self):
        self.server, self.url = serve(self._H)
        return self

    def stop(self):
        stop(self.server)

    # -- commands ------------------------------------------------------------------
    def run(self, cmd):
        name, key, *args = cmd
        name = name.upper()
        if name == "LPUSH":
            self.data.setdefault(key, [])
            for a in args:
                self.data[key].insert(0, a)
            return len(self.data[key])
        if name == "LTRIM":
            lo, hi = int(args[0]), int(args[1])
            lst = self.data.get(key, [])
            self.data[key] = lst[lo : hi + 1 if hi >= 0 else None]
            return "OK"
        if name == "LRANGE":
            lo, hi = int(args[0]), int(args[1])
            lst = self.data.get(key, [])
            return lst[lo : hi + 1 if hi >= 0 else None]
        if name == "HSET":
            h = self.data.setdefault(key, {})
            added = 0
            for f, v in zip(args[0::2], args[1::2]):
                added += f not in h
                h[f] = v
            return added
        if name == "HGETALL":
            flat = []
            for f, v in self.data.get(key, {}).items():
                flat += [f, v]
            return flat
        if name == "SET":  # SET key value [EX seconds] [NX]
            value, rest = args[0], [str(a).upper() for a in args[1:]]
            if "NX" in rest and key in self.data:
                return None
            self.data[key] = str(value)
            if "EX" in rest:
                self.expiry[key] = int(args[1:][rest.index("EX") + 1])
            return "OK"
        if name == "INCR":
            self.data[key] = str(int(self.data.get(key, 0)) + 1)
            return int(self.data[key])
        raise ValueError(f"unknown command {name}")


def make_pdf(text):
    """A one-page PDF built by hand. With ``text`` its text is real (extractable); with ``None`` the page only draws a shape, like a menu whose
    letters were converted to outlines."""
    draw = f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET" if text is not None else "0.2 0.2 0.2 rg 50 600 300 100 re f"
    stream = draw.encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
