# -*- coding: utf-8 -*-
"""本地打包：把 server/ 里「服务端真正需要的东西」压成 tianma-server.tar.gz

在 Windows 上跑（项目根目录）：
    python server/deploy/pack_for_upload.py

然后按打印出来的 scp 命令传到服务器即可。
排除了：data/（数据库）、logs/、__pycache__、test_*.py、_*.py、*.bak、*.swbak
"""
import io
import os
import sys
import tarfile

SRV = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # .../server
ROOT = os.path.dirname(SRV)                                          # 项目根
OUT = os.path.join(ROOT, "tianma-server.tar.gz")

SKIP_DIRS = {"data", "logs", "__pycache__", ".git", "backup"}
SKIP_SUFFIX = (".bak", ".swbak", ".pyc", ".log", ".db", ".db-wal", ".db-shm", ".bat")


def keep(name: str) -> bool:
    if name.startswith("test_") or name.startswith("_"):
        return False
    return not name.endswith(SKIP_SUFFIX)


TEXT_EXT = (".sh", ".service", ".md", ".json", ".py", ".sql", ".cfg", ".txt")


def add_as_lf(tf, full, arc):
    """文本文件统一转成 LF 再进包。

    ★ Windows 上写出来的脚本是 CRLF；Linux 的 bash 会把 `pipefail\r` 当成一个
      选项名，直接报 `invalid option name`。.service 带 \r 时 systemd 也可能读歪。
      所以在打包这一步就把换行修正，别指望服务器端去 sed。
    """
    data = open(full, "rb").read().replace(b"\r\n", b"\n")
    ti = tarfile.TarInfo(arc)
    ti.size = len(data)
    ti.mode = 0o755 if full.endswith(".sh") else 0o644
    ti.mtime = int(os.path.getmtime(full))
    tf.addfile(ti, io.BytesIO(data))


def main() -> int:
    count = 0
    with tarfile.open(OUT, "w:gz") as tf:
        for dirpath, dirnames, filenames in os.walk(SRV):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                if not keep(fn):
                    continue
                full = os.path.join(dirpath, fn)
                arc = os.path.join("server", os.path.relpath(full, SRV))
                arc = arc.replace("\\", "/")
                if fn.endswith(TEXT_EXT):
                    add_as_lf(tf, full, arc)
                else:
                    tf.add(full, arcname=arc)
                count += 1
    size = os.path.getsize(OUT) / 1024.0 / 1024.0
    print("打包完成：%s" % OUT)
    print("  文件数 %d，大小 %.2f MB" % (count, size))
    print()
    print("传到服务器（把 IP 换成你的）：")
    print("  scp \"%s\" root@你的服务器IP:/tmp/" % OUT)
    print()
    print("服务器上：")
    print("  cd /tmp && tar xzf tianma-server.tar.gz && cd server/deploy")
    print("  sudo bash install.sh            # 有域名 / 要走 Caddy")
    print("  sudo bash install.sh --public   # 暂时没域名，直接对外开 8000")
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.exit(main())
