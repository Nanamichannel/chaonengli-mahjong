# -*- coding: utf-8 -*-
"""一条命令起「本地调试环境」：本地服务端 + 让 F5 只连本地（不碰云端 / 不碰你的联机房间）。

为什么要有它（2026-11-08 真实教训）：
  · 想在编辑器里试【海底】特效，但 F5 会读 `user://net.cfg` → 直接连云端，
    还可能因为 `user://room.txt` 进到**你正在玩的房间**里搅局。
  · 客户端找配置的顺序是：`<Godot 编辑器/游戏 exe 所在目录>/net.cfg` → `user://net.cfg`。
    所以只要在**编辑器目录**放一个 net.cfg，就只影响 F5，不影响导出的 exe。
  · `user://room.txt`（大厅记住的房间号）优先级**高于** net.cfg 的 room，
    所以要单独隔离一下（本脚本会临时移走 + 退出时还原）。

用法：
    python tools/dev_local.py start     # 起本地服务端(8000) + 写编辑器 net.cfg + 隔离 room.txt
    python tools/dev_local.py status    # 现在是什么状态
    python tools/dev_local.py stop      # 关服务端 + 删编辑器 net.cfg + 还原 room.txt

注意：`start` 之后 F5 会进本地房间 `dev_box`（独立数据库 server/data/room_dev_box.db）。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(ROOT, "server")
LOG = os.path.join(r"N:\apps\_tmp", "net_dev.log")
PORT = 8000
ROOM = "dev_box"
GODOT_DIR = os.environ.get("GODOT_DIR", r"N:\apps\Godot_v4.7.2-stable_mono_win64")
EDITOR_CFG = os.path.join(GODOT_DIR, "net.cfg")
USER_DIR = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "Godot",
                        "app_userdata", "Tianma")
ROOM_MEMO = os.path.join(USER_DIR, "room.txt")
ROOM_BAK = ROOM_MEMO + ".dev_bak"


def _health() -> dict | None:
    try:
        raw = urllib.request.urlopen("http://127.0.0.1:%d/health" % PORT, timeout=2).read()
        return json.loads(raw.decode("utf-8", "replace"))
    except Exception:                                     # noqa: BLE001
        return None


def _pid_on_port(port: int) -> list[int]:
    p = subprocess.run(["netstat", "-ano"], capture_output=True)
    out = p.stdout.decode("utf-8", "replace")
    pids = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and (":%d" % port) in parts[1] and parts[3] == "LISTENING":
            if parts[4].isdigit() and parts[4] != "0":
                pids.add(int(parts[4]))
    return sorted(pids)


def cmd_start(_args) -> int:
    h = _health()
    if h is None:
        if not os.path.isdir(SERVER_DIR):
            print("找不到服务端目录：%s" % SERVER_DIR)
            return 2
        log = open(LOG, "w", encoding="utf-8", errors="replace")
        subprocess.Popen([sys.executable, "net_server.py", "--port", str(PORT)],
                         cwd=SERVER_DIR, stdout=log, stderr=subprocess.STDOUT)
        for _ in range(40):
            time.sleep(0.5)
            h = _health()
            if h is not None:
                break
        if h is None:
            print("服务端起不来，看日志：%s" % LOG)
            return 2
        print("本地服务端已启动：http://127.0.0.1:%d   （日志 %s）" % (PORT, LOG))
    else:
        print("本地服务端已在跑：http://127.0.0.1:%d" % PORT)

    # ① 编辑器专用 net.cfg（只影响 F5，不影响导出 exe）
    bak = EDITOR_CFG + ".bak_devlocal"
    if os.path.exists(EDITOR_CFG) and not os.path.exists(bak):
        shutil.copyfile(EDITOR_CFG, bak)
    with open(EDITOR_CFG, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"url": "http://127.0.0.1:%d" % PORT, "room": ROOM, "token": "",
                   "timeout_ms": 10000}, f, ensure_ascii=False, indent=2)
    print("已写编辑器 net.cfg → %s（room=%s）" % (EDITOR_CFG, ROOM))

    # ② 隔离 user://room.txt（它的优先级高于 net.cfg 的 room，会把你带进联机房间）
    if os.path.exists(ROOM_MEMO) and not os.path.exists(ROOM_BAK):
        shutil.move(ROOM_MEMO, ROOM_BAK)
        print("已临时移走 user://room.txt（→ room.txt.dev_bak），F5 不会进你的联机房间")
    print("\n现在按 F5 即可；玩完记得： python tools/dev_local.py stop")
    return 0


def cmd_stop(_args) -> int:
    pids = _pid_on_port(PORT)
    for pid in pids:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    print("端口 %d 已释放（pid %s）" % (PORT, pids or "无"))

    if os.path.exists(EDITOR_CFG):
        os.remove(EDITOR_CFG)
        print("已删编辑器 net.cfg")
    bak = EDITOR_CFG + ".bak_devlocal"
    if os.path.exists(bak):
        shutil.move(bak, EDITOR_CFG)
        print("已还原原来的编辑器 net.cfg")

    if os.path.exists(ROOM_BAK):
        if os.path.exists(ROOM_MEMO):
            os.remove(ROOM_MEMO)
        shutil.move(ROOM_BAK, ROOM_MEMO)
        print("已还原 user://room.txt = %s" % open(ROOM_MEMO, encoding="utf-8").read().strip())
    return 0


def cmd_status(_args) -> int:
    h = _health()
    print("本地服务端  : %s" % ("在跑 → http://127.0.0.1:%d  rooms=%s"
                              % (PORT, ",".join(h.get("rooms", []))) if h else "没起"))
    print("编辑器 net.cfg: %s" % ("存在（F5 只会连本地）" if os.path.exists(EDITOR_CFG) else "不存在"))
    print("room.txt    : %s" % ("已隔离（.dev_bak）" if os.path.exists(ROOM_BAK) else "正常"))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["start", "stop", "status"])
    a = ap.parse_args()
    return {"start": cmd_start, "stop": cmd_stop, "status": cmd_status}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
