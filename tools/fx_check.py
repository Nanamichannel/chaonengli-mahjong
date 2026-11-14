# -*- coding: utf-8 -*-
"""特效视频（.ogv）体检 —— 每条流水线跑完必须过这一关。

为什么要有它（2026-11-08 真实教训）：
  · 【海底】收尾段 `haidi_out_v*.ogv` 只编出 2.0 秒（应为 7.17 秒），
    客户端播放器 2 秒就 `finished` → 冻结 + 跳结算，收尾动画根本没演完。
    **肉眼在游戏里很难发现「少了 5 秒」**，但一条 `时长 ≠ 帧数/fps` 检查就能立刻抓到。
  · 换段时黑一帧：因为 v1（相乘层的乘数）在换段后那一帧是全黑的空纹理。
    这里顺手把每段「首帧 / 末帧」的亮度打出来 + 检查段间连续性。

用法：
    python tools/fx_check.py                        # 默认查 Cailiao/UI/haidi
    python tools/fx_check.py --dir <目录>            # 查别的目录
    python tools/fx_check.py --frames in=672,loop=66,out=430 --fps 60
    python tools/fx_check.py --multiplier v1         # 哪一路是「乘数」（默认 v1）

退出码：0 = 全过；1 = 有问题（时长不对 / 乘数层太黑 / 段间不连续）。
依赖：imageio-ffmpeg（服务器测试环境里已装）。
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
try:
    import imageio_ffmpeg
except ImportError:                                     # pragma: no cover
    print("缺 imageio-ffmpeg：pip install imageio-ffmpeg")
    raise SystemExit(2)

DEFAULT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "Cailiao", "UI", "haidi")
FF = imageio_ffmpeg.get_ffmpeg_exe()

NAME_RE = re.compile(r"^(?P<base>.+)_(?P<seg>[a-z]+)_(?P<ch>v\d)$")


def probe(path: str) -> dict:
    """解一遍：时长、解码帧数、首帧/末帧的中心像素均值。"""
    p = subprocess.run([FF, "-hide_banner", "-i", path, "-f", "null", "-"],
                       capture_output=True)
    err = p.stderr.decode("utf-8", "replace")
    frames = re.search(r"frame=\s*(\d+)", err)
    dur = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", err)
    secs = 0.0
    if dur:
        secs = int(dur.group(1)) * 3600 + int(dur.group(2)) * 60 + float(dur.group(3))
    return {"frames": int(frames.group(1)) if frames else -1, "secs": secs,
            "size": os.path.getsize(path)}


def frame_mean(path: str, idx: int, w: int, h: int) -> float | None:
    """取第 idx 帧的 (R+G+B)/3 均值；取不到返回 None。"""
    cmd = [FF, "-hide_banner", "-loglevel", "error", "-i", path,
           "-vf", "select=eq(n\\,%d)" % idx, "-frames:v", "1",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    p = subprocess.run(cmd, capture_output=True)
    buf = p.stdout
    n = w * h * 3
    if len(buf) < n:
        return None
    return (sum(buf[0::3]) + sum(buf[1::3]) + sum(buf[2::3])) / (3.0 * w * h * 255.0)


def video_wh(path: str) -> tuple[int, int]:
    p = subprocess.run([FF, "-hide_banner", "-i", path], capture_output=True)
    m = re.search(r"Video:.*?,\s*(\d+)x(\d+)", p.stderr.decode("utf-8", "replace"))
    return (int(m.group(1)), int(m.group(2))) if m else (640, 360)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=DEFAULT_DIR)
    ap.add_argument("--fps", type=float, default=60.0)
    ap.add_argument("--frames", default="in=658,loop=66,out=430",
                    help="每段应有的帧数（时长 ≈ 帧数/fps）")
    ap.add_argument("--multiplier", default="v1",
                    help="哪一路是「乘数」（它黑 = 整屏黑）")
    ap.add_argument("--dark", type=float, default=0.05,
                    help="乘数层首/末帧低于这个亮度就报警")
    ap.add_argument("--jump", type=float, default=0.08,
                    help="乘数层段间跳变超过这个就报警")
    args = ap.parse_args()

    want = {}
    for kv in args.frames.split(","):
        k, v = kv.split("=")
        want[k.strip()] = int(v)

    files = sorted(f for f in os.listdir(args.dir) if f.endswith(".ogv"))
    if not files:
        print("目录里没有 .ogv：%s" % args.dir)
        return 1

    bad: list[str] = []
    info: dict[str, dict] = {}
    print("%-22s %8s %7s %9s %8s %8s" % ("文件", "时长(s)", "应有", "解码帧", "首帧", "末帧"))
    print("-" * 72)
    for f in files:
        path = os.path.join(args.dir, f)
        d = probe(path)
        m = NAME_RE.match(f[:-4])
        seg = m.group("seg") if m else "?"
        ch = m.group("ch") if m else "?"
        w, h = video_wh(path)
        first = frame_mean(path, 0, w, h)
        last = frame_mean(path, max(d["frames"] - 1, 0), w, h)
        exp = want.get(seg)
        exp_sec = (exp / args.fps) if exp else 0.0
        prev = first if first is not None else -1.0
        lastv = last if last is not None else -1.0
        print("%-22s %8.2f %7s %9d %8.3f %8.3f"
              % (f, d["secs"], ("%.2f" % exp_sec) if exp else "-", d["frames"], prev, lastv))
        info[f] = {"seg": seg, "ch": ch, "secs": d["secs"], "first": prev, "last": lastv}
        # ① 时长
        if exp and abs(d["secs"] - exp_sec) > max(0.12, exp_sec * 0.02):
            bad.append("%s 时长 %.2fs ≠ 应有 %.2fs（%d 帧 / %.0ffps）"
                       % (f, d["secs"], exp_sec, exp, args.fps))
        # ② 乘数层不能太黑（黑了 = 整屏黑）
        if ch == args.multiplier and (prev < args.dark or lastv < args.dark):
            bad.append("%s 是乘数层但首/末帧太黑（%.3f / %.3f）→ 播到会整屏黑"
                       % (f, prev, lastv))

    # ③ 段间连续性（只比乘数层）：in→loop→out 按这个顺序
    order = [s for s in ("in", "loop", "out") if any(v["seg"] == s for v in info.values())]
    key = {}
    for f, v in info.items():
        if v["ch"] == args.multiplier:
            key[v["seg"]] = v
    for a, b in zip(order, order[1:]):
        if a in key and b in key:
            jump = abs(key[a]["last"] - key[b]["first"])
            if jump > args.jump:
                bad.append("%s 末帧(%.3f) → %s 首帧(%.3f) 跳变 %.3f > %.2f（会看见跳/闪）"
                           % (a, key[a]["last"], b, key[b]["first"], jump, args.jump))

    print("-" * 72)
    if bad:
        print("发现 %d 个问题：" % len(bad))
        for b in bad:
            print("  ✗ " + b)
        return 1
    print("✓ 全部通过（时长 / 乘数层亮度 / 段间连续性）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
