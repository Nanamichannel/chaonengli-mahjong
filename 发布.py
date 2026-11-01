# -*- coding: utf-8 -*-
"""一键发布：生成**单文件** Tianma.exe（口令内置，朋友不用带 net.cfg）

为什么需要它：
    仓库是公开的，`server_net.gd` 里的 `DEFAULT_TOKEN` 故意留空（不然口令进
    GitHub 等于公开）。但发给朋友时又不想让他们放两个文件，所以导出前临时把
    口令填进去、导完立刻改回来 —— 源码始终是干净的。

用法（项目根目录）：
    python 发布.py

产物：
    build/Tianma.exe    单文件，双击即玩（内置地址 + 内置口令）
"""
import io
import json
import os
import subprocess
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))
NET_GD = os.path.join(ROOT, "server_net.gd")
OUT = os.path.join(ROOT, "build", "Tianma.exe")
GODOT = r"N:\apps\Godot_v4.7.2-stable_mono_win64\Godot_v4.7.2-stable_mono_win64.exe"
PRESET = "天才麻将少女！"

# 服务器参数：地址写死（换服务器改这行）；口令**不写在这里**（仓库是公开的），
# 从下面两个地方按顺序找：
#   ① 环境变量 TIANMA_TOKEN
#   ② build/net.cfg 里的 "token"（这个文件被 .gitignore 排除，本地放一份就行）
URL = "http://115.159.39.131:8000"


def _read_token() -> str:
    t = os.environ.get("TIANMA_TOKEN", "").strip()
    if t:
        return t
    cfg = os.path.join(ROOT, "build", "net.cfg")
    if os.path.exists(cfg):
        try:
            d = json.loads(open(cfg, encoding="utf-8").read())
            return str(d.get("token", "")).strip()
        except Exception:
            pass
    return ""

EMPTY_TOKEN = 'const DEFAULT_TOKEN := ""'
FILLED_TOKEN = 'const DEFAULT_TOKEN := "%s"' % TOKEN


def main() -> int:
    if not os.path.exists(GODOT):
        print("找不到 Godot：%s" % GODOT)
        return 1

    token = _read_token()
    if not token:
        print("找不到房间口令。二选一：")
        print("  · 设置环境变量：set TIANMA_TOKEN=你的口令")
        print("  · 或者写 build/net.cfg：{\"url\": \"%s\", \"room\": \"default\", \"token\": \"...\"}" % URL)
        return 1

    src = open(NET_GD, encoding="utf-8").read()
    if EMPTY_TOKEN not in src:
        print("server_net.gd 里没找到 `%s` —— 可能已经被改过，先检查一下。" % EMPTY_TOKEN)
        return 1

    # 1) 先把正在运行的旧 exe 关掉（Windows 不让覆盖）
    subprocess.run(["taskkill", "/IM", "Tianma.exe", "/F"],
                   capture_output=True)
    time.sleep(1)

    # 2) 临时填入口令 → 导出 → 立刻恢复
    patched = src.replace(EMPTY_TOKEN, 'const DEFAULT_TOKEN := "%s"' % token)
    try:
        open(NET_GD, "w", encoding="utf-8", newline="\n").write(patched)
        t0 = time.time()
        p = subprocess.run([GODOT, "--headless", "--path", ROOT,
                            "--export-release", PRESET, OUT],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=1800)
        dt = time.time() - t0
    finally:
        open(NET_GD, "w", encoding="utf-8", newline="\n").write(src)

    if p.returncode != 0:
        print("导出失败（rc=%d）：" % p.returncode)
        for line in ((p.stdout or "") + (p.stderr or "")).splitlines():
            if "ERROR" in line or "失败" in line:
                print("   ", line[:160])
        return 1

    size = os.path.getsize(OUT) / 1048576.0
    print("✅ 发布完成：%s" % OUT)
    print("   %.1f MB，用时 %.1f 秒" % (size, dt))
    print("   内置地址：%s" % URL)
    print("   内置口令：%s…（已内置）" % token[:10])
    print("   源码里仍然是空口令 —— 可以直接 git push")

    # 3) 顺便确认 build/net.cfg 存在也无所谓（值一样，不会互相干扰）
    cfg = os.path.join(ROOT, "build", "net.cfg")
    if os.path.exists(cfg):
        print("   提示：build/net.cfg 还在，但 exe 已经自带口令，带不带它都行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
