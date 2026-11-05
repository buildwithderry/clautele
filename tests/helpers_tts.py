"""Helper bersama untuk tes TTS: server HTTP tiruan di loopback dan pembuat WAV."""

import io
import json
import math
import struct
import threading
import wave
from http.server import BaseHTTPRequestHandler, HTTPServer

SECRET = "sup3r-secret-pass"


def make_wav(seconds=0.5, rate=16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 20))) for i in range(int(rate * seconds))))
    return buf.getvalue()


class Server:
    """Server HTTP tiruan di loopback; perilakunya diatur per tes lewat atribut."""

    def __init__(self):
        self.requests: list[dict] = []
        self.mode = "ok"
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _handle(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                outer.requests.append({"method": self.command, "path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
                m = outer.mode
                if m == "401":
                    return self._send(401, b"401 Unauthorized", "text/plain")
                if m == "500":
                    return self._send(500, b"boom di server", "text/plain")
                if m == "redirect":
                    self.send_response(302)
                    self.send_header("Location", outer.redirect_to)
                    self.end_headers()
                    return
                if m == "slow":
                    import time

                    time.sleep(3)
                if self.path == "/health":
                    return self._send(200, b'{"status":"ok"}', "application/json")
                if self.path in ("/engines", "/models"):
                    return self._send(200, b'[{"id":"omni-tts"}]', "application/json")
                if self.path == "/openapi.json":
                    paths = {"/v1/audio/speech": {}, "/voices/profiles": {}, "/system/admin": {}, "/health": {}}
                    return self._send(200, json.dumps({"paths": paths}).encode(), "application/json")
                if self.path == "/v1/audio/speech":
                    if m == "json":
                        return self._send(200, b'{"error":"voice tidak ada"}', "application/json")
                    if m == "notaudio":
                        return self._send(200, b"<html>halo</html>", "audio/wav")
                    if m == "big":
                        return self._send(200, b"RIFF" + b"x" * 5000, "audio/wav")
                    return self._send(200, make_wav(), "audio/wav")
                self._send(404, b"nope", "text/plain")

            do_GET = do_POST = _handle

            def _send(self, code, data, ctype):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.redirect_to = ""
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
