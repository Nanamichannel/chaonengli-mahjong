#!/usr/bin/env bash
# 天马麻将 服务端一键安装（Ubuntu 22.04 / 24.04，Debian 12 同样可用）
#
# 用法：把整个 server 目录传到服务器后
#   cd server/deploy
#   sudo bash install.sh            # 默认：只监听 127.0.0.1:8000（配合 Caddy 用）
#   sudo bash install.sh --public   # 直接对外监听 0.0.0.0:8000（没有域名时用）
#
# 幂等：重复执行只会更新代码 + 重启服务，不会动数据库。
set -euo pipefail

APP_DIR=/opt/tianma
SVC_USER=tianma
PORT=8000
PUBLIC=0
if [ "${1:-}" = "--public" ]; then PUBLIC=1; fi

echo "==> 1/6 检查 Python"
PY=$(command -v python3 || true)
[ -n "$PY" ] || { echo "!! 没装 python3，先 apt-get update && apt-get install -y python3"; exit 1; }
VER=$($PY -c 'import sys;print("%d.%d"%sys.version_info[:2])')
echo "    python3 = $VER ($PY)"
$PY -c 'import sys;sys.exit(0 if sys.version_info>=(3,9) else 1)' || {
  echo "!! 需要 Python 3.9+（推荐 3.10+），当前 $VER"; exit 1; }

echo "==> 2/6 建专用用户 $SVC_USER"
if ! id -u "$SVC_USER" >/dev/null 2>&1; then
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$SVC_USER"
  echo "    已创建"
else
  echo "    已存在"
fi

echo "==> 3/6 拷代码到 $APP_DIR/server"
SRC="$(cd "$(dirname "$0")/.." && pwd)"          # .../server
mkdir -p "$APP_DIR/server/data" "$APP_DIR/server/logs"
cd "$SRC"
for f in *.py *.sql *.json; do
  [ -e "$f" ] || continue
  case "$f" in test_*|_*|*.bak|*.swbak) continue ;; esac
  cp -f "$f" "$APP_DIR/server/"
done
if [ -d rules ]; then
  mkdir -p "$APP_DIR/server/rules"
  cp -rf rules/. "$APP_DIR/server/rules/"
fi
# 没配置文件就按示例建一份（token 留空 = 不校验，公网请填上）
if [ ! -f "$APP_DIR/server/net_config.json" ]; then
  cp -f net_config.example.json "$APP_DIR/server/net_config.json"
  echo "    已生成 net_config.json（公网部署请把 token 改成你自己的口令）"
fi
chown -R "$SVC_USER:$SVC_USER" "$APP_DIR"
echo "    代码文件数：$(find "$APP_DIR/server" -maxdepth 1 -name '*.py' | wc -l)"

echo "==> 4/6 装 systemd 服务"
HOST=127.0.0.1
if [ "$PUBLIC" = "1" ]; then HOST=0.0.0.0; fi
sed -e "s|__HOST__|$HOST|g" -e "s|__PORT__|$PORT|g" -e "s|__USER__|$SVC_USER|g" \
    -e "s|__APP_DIR__|$APP_DIR|g" -e "s|__PY__|$PY|g" \
    "$SRC/deploy/tianma.service" > /etc/systemd/system/tianma.service
systemctl daemon-reload
systemctl enable tianma >/dev/null
systemctl restart tianma
sleep 2

echo "==> 5/6 自检"
if curl -sf -m 5 "http://127.0.0.1:$PORT/health" >/dev/null; then
  echo "    ✅ 服务起来了：$(curl -s -m 5 http://127.0.0.1:$PORT/health)"
else
  echo "    ❌ 起不来，看日志： journalctl -u tianma -n 50 --no-pager"
  exit 1
fi

echo "==> 6/6 提示"
if [ "$PUBLIC" = "1" ]; then
  echo "    现在对外监听 0.0.0.0:$PORT"
  echo "    · 云控制台安全组 + 本机防火墙都要放行 $PORT"
  echo "    · 客户端：net.cfg 里 url 写 http://<公网IP>:$PORT"
else
  echo "    只监听 127.0.0.1:$PORT（安全）"
  echo "    · 下一步装 Caddy 反代 + 自动 HTTPS，见 deploy/README.md 第 5 步"
fi
echo
echo "    日志：journalctl -u tianma -f"
echo "    状态：systemctl status tianma"
