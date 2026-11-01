# -*- coding: utf-8 -*-
"""服务端 → 客户端的长连接推送（最小 WebSocket 实现，零依赖）。

为什么自己写：服务端是 ThreadingHTTPServer 单端口（8000），
Tailscale Funnel 也只暴露这一个口。这里在 HTTP handler 里接住
`Upgrade: websocket`，同一个 socket 切成双向通道，不用另开端口、不用改 Funnel。

协议范围（够用就行）：文本帧 + ping/pong/close，不支持分片和扩展。
"""
import base64
import hashlib
import json
import struct
import threading
import time
import zlib

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

_lock = threading.Lock()
_rooms: dict[str, set] = {}      # room -> set[_Conn]
_last_ver: dict[str, str] = {}   # room -> 上次推过的 ver（防「轮询→推送→再轮询」自激）


class _Conn:
    def __init__(self, handler):
        self.handler = handler
        self.sock = handler.connection
        self.rfile = handler.rfile
        self.room = ""
        self.seat = -1
        self.alive = True
        self.wlock = threading.Lock()

    # ── 写 ──
    def send_text(self, text: str) -> bool:
        return self._frame(0x1, text.encode("utf-8"))

    def _frame(self, opcode: int, data: bytes) -> bool:
        n = len(data)
        head = bytearray([0x80 | opcode])
        if n < 126:
            head.append(n)
        elif n < 65536:
            head.append(126)
            head += struct.pack(">H", n)
        else:
            head.append(127)
            head += struct.pack(">Q", n)
        try:
            with self.wlock:
                self.sock.sendall(bytes(head) + data)
            return True
        except Exception:                                    # noqa: BLE001
            self.alive = False
            return False

    # ── 读 ──
    def _read(self, n: int) -> bytes:
        try:
            return self.rfile.read(n)
        except Exception:                                    # noqa: BLE001
            return b""

    def read_frame(self):
        hdr = self._read(2)
        if not hdr or len(hdr) < 2:
            return (None, b"")
        b1, b2 = hdr[0], hdr[1]
        opcode = b1 & 0x0F
        masked = bool(b2 & 0x80)
        n = b2 & 0x7F
        if n == 126:
            ext = self._read(2)
            if len(ext) < 2:
                return (None, b"")
            n = struct.unpack(">H", ext)[0]
        elif n == 127:
            ext = self._read(8)
            if len(ext) < 8:
                return (None, b"")
            n = struct.unpack(">Q", ext)[0]
        key = b""
        if masked:
            key = self._read(4)
            if len(key) < 4:
                return (None, b"")
        data = self._read(n) if n else b""
        if n and len(data) < n:
            return (None, b"")
        if masked and data:
            data = bytes(b ^ key[i % 4] for i, b in enumerate(data))
        return (opcode, data)


def handle_upgrade(handler, room: str, hello: dict | None = None,
                   seat: int = -1) -> None:
    """在 HTTP handler 里做 WS 握手，然后一直服务到断开。"""
    key = handler.headers.get("Sec-WebSocket-Key", "")
    if not key:
        handler._send(400, {"ok": False, "error": "缺少 Sec-WebSocket-Key"})
        return
    acc = base64.b64encode(
        hashlib.sha1((key + GUID).encode("utf-8")).digest()).decode("ascii")
    try:
        handler.send_response(101, "Switching Protocols")
        handler.send_header("Upgrade", "websocket")
        handler.send_header("Connection", "Upgrade")
        handler.send_header("Sec-WebSocket-Accept", acc)
        handler.end_headers()
    except Exception:                                        # noqa: BLE001
        return
    handler.close_connection = True
    try:
        handler.connection.settimeout(120)                   # 死连接别一直占线程
    except Exception:                                        # noqa: BLE001
        pass

    conn = _Conn(handler)
    conn.room = room
    conn.seat = int(seat)
    with _lock:
        _rooms.setdefault(room, set()).add(conn)
        n = len(_rooms[room])
    if hello:
        conn.send_text(json.dumps(hello, ensure_ascii=False))

    try:
        while conn.alive:
            op, data = conn.read_frame()
            if op is None or op == 0x8:
                break
            if op == 0x9:                                    # ping → pong
                conn._frame(0xA, data)
            elif op == 0x1:                                  # 客户端「我在」→ 回 pong
                conn.send_text('{"pong":1}')
    except Exception:                                        # noqa: BLE001
        pass
    finally:
        conn.alive = False
        with _lock:
            s = _rooms.get(room)
            if s is not None:
                s.discard(conn)
                if not s:
                    _rooms.pop(room, None)
        try:
            handler.connection.close()
        except Exception:                                    # noqa: BLE001
            pass


def notify(room: str, ver: str, payloads: dict | None = None) -> int:
    """状态变了 → 推给这个房间的长连接。

    payloads: {seat: 该座位的响应字典}。有就用**二进制帧 + zlib**把整份 state 推过去
    （每人一份，视野已经裁过），客户端收到直接渲染，不用再拉一次。
    缺这个座位（或没给 payloads）就退回「只推版本号」，客户端被叫醒后自己 poll。
    同一个 ver 只推一次。
    """
    if not ver:
        return 0
    with _lock:
        if _last_ver.get(room) == ver:
            return 0
        _last_ver[room] = ver
        conns = list(_rooms.get(room) or ())
    if not conns:
        return 0
    simple = json.dumps({"push": "state", "room": room, "ver": ver, "ts": time.time()},
                        ensure_ascii=False)
    sent = 0
    for c in conns:
        body = None
        if payloads:
            p = payloads.get(c.seat) if c.seat >= 0 else None
            if isinstance(p, dict):
                p = dict(p)
                p["push"] = "state"
                p["room"] = room
                full = json.dumps(p, ensure_ascii=False).encode("utf-8")
                try:
                    body = zlib.compress(full, 6)
                except Exception:                            # noqa: BLE001
                    body = None
        ok = c._frame(0x2, body) if body else c.send_text(simple)
        if ok:
            sent += 1
        else:
            c.alive = False
    return sent


def live_seats(room: str) -> set:
    """这个房间里**真的连着**的座位号（-1 = 没认领座位的不算）。

    net_server 用它决定「动作之后要给几个人算 state」——
    以前不管有没有人连，一律算 4 份，单人玩的时候 3 份纯属白干。
    """
    with _lock:
        return {int(c.seat) for c in (_rooms.get(room) or ())
                if c.alive and int(c.seat) >= 0}


def peers(room: str | None = None) -> int:
    with _lock:
        if room is None:
            return sum(len(v) for v in _rooms.values())
        return len(_rooms.get(room) or ())
