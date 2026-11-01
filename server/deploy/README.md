# 部署到云服务器（照抄版）

> 目标机器：Ubuntu 22.04 / 24.04（Debian 12 也一样）。2 核 4G 够用。
> 服务端零第三方依赖，只要有 `python3`（3.9+，Ubuntu 24.04 自带 3.12）。

---

## 0. 先准备好这三样

| 需要 | 说明 |
|---|---|
| 服务器公网 IP | 云控制台能看到 |
| SSH 账号 | 一般是 `root`，或带 sudo 的普通用户 |
| 域名（可选） | 有域名才能用 HTTPS；没有就先用 `http://IP:8000`，但 token 会明文传 |

---

## 1. 本地打包（Windows）

项目根目录执行：

```powershell
python server\deploy\pack_for_upload.py
```

会生成 `tianma-server.tar.gz`（约 200 KB，已排除测试脚本、数据库、日志），
并打印出下一步的 scp 命令。

---

## 2. 传到服务器

```powershell
scp .\tianma-server.tar.gz root@你的服务器IP:/tmp/
```

> Windows 10/11 自带 `scp`。第一次连会问 `yes/no`，输 `yes`。

---

## 3. 服务器上跑安装脚本

```bash
ssh root@你的服务器IP

cd /tmp
tar xzf tianma-server.tar.gz
cd server/deploy

# 有域名 / 打算挂 Caddy：
sudo bash install.sh

# 暂时没域名，就想先让朋友用 IP 连：
sudo bash install.sh --public
```

脚本会做 6 件事：检查 Python → 建 `tianma` 专用用户 → 拷代码到 `/opt/tianma/server`
→ 装 systemd 服务 → 重启 → 自检 `/health`。

成功的样子：

```
==> 5/6 自检
    ✅ 服务起来了：{"ok": true, "rooms": ["default"], "default": "default", "ts": ..., "peers": {"default": 0}, "push_total": 0}
```

---

## 4. 放行端口（**两层都要**）

### 4.1 云控制台「安全组 / 防火墙」
- 22（SSH）
- 80（HTTP，申请证书要用）
- 443（HTTPS）
- **8000 不要开**（除非用 `--public` 模式，那种情况才开 8000）

### 4.2 服务器本机防火墙

```bash
sudo apt install -y ufw
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

> ⚠️ 用 `--public` 模式的话，这里再加一条 `sudo ufw allow 8000/tcp`。

---

## 5. 挂域名 + 自动 HTTPS（推荐）

### 5.1 域名解析
在域名商后台加一条 A 记录：`mahjong.你的域名.com → 服务器公网 IP`。
验证：本机 `ping mahjong.你的域名.com` 能出这个 IP。

### 5.2 装 Caddy

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
```

### 5.3 写配置

```bash
sudo cp /opt/tianma/server/deploy/Caddyfile /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile      # 把第一行 mahjong.example.com 改成你的域名
sudo systemctl reload caddy
sudo systemctl status caddy --no-pager
```

Caddy 会自动申请 Let's Encrypt 证书（**并且自动处理 WebSocket 升级**，不用手写 Upgrade 头）。

验证：

```bash
curl https://mahjong.你的域名.com/health
```

---

## 6. 给房间设口令（公网必做）

```bash
sudo nano /opt/tianma/server/net_config.json
```

```json
{
  "allow_auto_rooms": false,
  "default_room": "default",
  "rooms": {
    "default": { "token": "换成你自己的口令", "db": "data/mahjong.db" }
  }
}
```

```bash
sudo systemctl restart tianma
```

**`allow_auto_rooms` 一定要是 `false`**：开着的话，任何人请求 `/rpc/随便什么名字`
都会自动开一个**不带口令**的新房间 —— 等于把 token 绕过去了。
关掉之后，只有上面 `rooms` 里列出的房间能访问，其余一律 404。

验证（两条都要对）：

```bash
curl -s -o /dev/null -w "无口令:   %{http_code}\n" -X POST http://127.0.0.1:8000/rpc/default \
  -H "Content-Type: application/json" -d '{"op":"state","seat":0}'     # 期望 403
curl -s -o /dev/null -w "陌生房间: %{http_code}\n" -X POST http://127.0.0.1:8000/rpc/hack \
  -H "Content-Type: application/json" -d '{"op":"state","seat":0}'     # 期望 404
```

客户端在 `net.cfg` 里带上同样的 token（见第 9 步）。

---

## 7. 日常运维

```bash
# 看日志（实时）
journalctl -u tianma -f

# 服务状态
systemctl status tianma

# 重启 / 停止
sudo systemctl restart tianma
sudo systemctl stop tianma

# 健康检查
curl -s https://你的域名/health
```

**关键指标：`peers`**
```json
{"peers": {"default": 4}, "push_total": 4}
```
- `peers` 有数字 = WebSocket 长连接正常
- 全是 0 但玩家能玩 = 推送没通（反代问题），流量会涨约 40%

---

## 8. 备份（强烈建议）

```bash
sudo apt install -y sqlite3
sudo chmod +x /opt/tianma/server/deploy/backup.sh
sudo crontab -e
```

加一行（每天凌晨 4 点）：

```
0 4 * * * /opt/tianma/server/deploy/backup.sh >> /var/log/tianma-backup.log 2>&1
```

> SQLite 在 WAL 模式下**不能直接 `cp`**（会拿到不一致的快照），`backup.sh` 用的是
> `sqlite3 .backup`，正在写也安全。默认保留 14 天，放 `/opt/tianma/backup/`。

---

## 9. 客户端怎么连

### 9.1 临时试（单个玩家）

把 `net.cfg` 放到 **exe 同目录**：

```json
{
  "url": "https://你的域名",
  "room": "default",
  "token": "跟服务端一致的口令",
  "timeout_ms": 10000
}
```

> 有 `net.cfg` 会覆盖程序内置地址；没有就用内置的 `DEFAULT_URL`。
> 房间号会被本机 `user://room.txt` 记住，优先级更高 —— 想强制换房间就改这个文件或删掉它。

### 9.2 正式发布

改 `server_net.gd:28`：

```gdscript
const DEFAULT_URL := "https://你的域名"
```

然后重新导出 exe（`export_presets.cfg` 里预设：天才麻将少女！→ `build/Tianma.exe`）。

---

## 10. 排错对照表

| 现象 | 原因 | 处理 |
|---|---|---|
| 浏览器 `http://IP:8000/health` 打不开 | 安全组/ufw 没放行，或用了默认（只听 127.0.0.1） | 放行端口，或改用 `--public` 装一次 |
| 客户端「加入大厅失败」 | 地址写错 / 服务没起 / 证书没下来 | `curl .../health` 先自己试；`journalctl -u tianma -f` 看请求 |
| `/health` 里 `peers` 一直 0 | 反代没转发 WebSocket | 用 Caddy（自动处理）；nginx 要写 `Upgrade`/`Connection` 头 |
| 4 个人进去全坐到 0 号位 | 座位租约拿客户端 pid 判活（公网必然查不到） | **已修**（`LEASE_PID_LOCAL_ONLY`），确保代码是 2026-11-01 之后的 |
| 打开技能面板后别人卡住 | 服务端在等这个座位作答 | 正常；该座位掉线 12 秒后会由服务器代打 |
| 磁盘慢慢变大 | 每人开过的房间各留一个库 | 服务启动时会清 72 小时没动过的 `room_*.db` |

---

## 11. 升级代码

```powershell
# 本地：重新打包
python server\deploy\pack_for_upload.py
scp .\tianma-server.tar.gz root@你的服务器IP:/tmp/
```

```bash
# 服务器：解包 + 重装（不会动 data/）
cd /tmp && tar xzf tianma-server.tar.gz && cd server/deploy
sudo bash install.sh
```

> `install.sh` 只覆盖 `*.py` / `rules/` / `*.sql` / 示例配置，**不会碰数据库**。
