#!/usr/bin/env python3
"""Minimal stdlib-only Chrome DevTools Protocol driver.

No third-party deps on purpose: the project's venv must stay untouched.
Speaks just enough RFC6455 to talk to Chrome's /devtools websocket.
"""
import base64
import json
import os
import socket
import struct
import subprocess
import sys
import time
import urllib.parse
import urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


class WS:
    def __init__(self, url):
        assert url.startswith("ws://")
        rest = url[5:]
        hostport, _, path = rest.partition("/")
        host, _, port = hostport.partition(":")
        self.sock = socket.create_connection((host, int(port or 80)))
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET /{path} HTTP/1.1\r\n"
            f"Host: {hostport}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("handshake failed")
            buf += chunk
        self.rest = buf.split(b"\r\n\r\n", 1)[1]
        self.buf = b""

    def _recv_exact(self, n):
        while len(self.rest) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("socket closed")
            self.rest += chunk
        out, self.rest = self.rest[:n], self.rest[n:]
        return out

    def send(self, text):
        payload = text.encode()
        n = len(payload)
        header = bytearray([0x81])
        mask = os.urandom(4)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def recv(self):
        while True:
            b1, b2 = self._recv_exact(2)
            opcode = b1 & 0x0F
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._recv_exact(8))[0]
            data = self._recv_exact(length)
            if opcode == 0x1:
                return data.decode()
            if opcode == 0x8:
                raise RuntimeError("closed by peer")


class CDP:
    def __init__(self, ws_url):
        self.ws = WS(ws_url)
        self._id = 0
        self.events = []

    def call(self, method, params=None, timeout=30):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method,
                                 "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method} failed: {msg['error']}")
                return msg.get("result", {})
            if "method" in msg:
                self.events.append(msg)
        raise TimeoutError(method)

    def evaluate(self, expr, timeout=20):
        r = self.call("Runtime.evaluate",
                      {"expression": expr, "returnByValue": True},
                      timeout=timeout)
        if "exceptionDetails" in r:
            raise RuntimeError(str(r["exceptionDetails"])[:300])
        return r.get("result", {}).get("value")

    def drain_events(self, want_prefix="Log."):
        out = [e for e in self.events if e.get("method", "").startswith(want_prefix)]
        self.events = []
        return out


def launch(port=9333, profile="/tmp/chrome-cdp-profile", width=1280, height=900,
           extra_args=None):
    """起一个无头 Chrome。

    extra_args:额外命令行参数。走自签 HTTPS 时要传
    ["--ignore-certificate-errors"] —— 截图不需要证书可信,
    但不忽略的话 Chrome 直接 ERR_CERT_AUTHORITY_INVALID,页面都打不开。
    """
    subprocess.run(["pkill", "-f", "chrome-cdp-profile"], capture_output=True)
    proc = subprocess.Popen([
        CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
        "--no-default-browser-check", "--hide-scrollbars",
        "--disable-features=Translate,MediaRouter",
        # 无头模式下没有用户手势,AudioContext 会停在 suspended:
        # 注入的 MediaStream 就没有声音,录出来是空文件。
        "--autoplay-policy=no-user-gesture-required",
        "--use-fake-ui-for-media-stream",
        "--use-fake-device-for-media-stream",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
        f"--window-size={width},{height}",
        "about:blank",
    ] + list(extra_args or []),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(80):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as r:
                json.load(r)
            break
        except Exception:
            time.sleep(0.25)
    else:
        raise RuntimeError("chrome did not expose devtools")
    return proc


def new_tab(port=9333, url="about:blank"):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/json/new?{urllib.parse.quote(url, safe='')}",
        method="PUT")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r)


if __name__ == "__main__":
    print("this module is meant to be imported")
