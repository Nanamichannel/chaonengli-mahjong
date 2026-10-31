# 超能力麻将！

Godot 4.7 客户端 + Python/SQLite 服务端的**日本麻将（立直麻将）**，带「技能卡（超能力）」变体玩法。

> 项目代号 **Tianma**，取自「天才麻将少女」。
> 核心设计原则：**规则只在服务端**。番符计算、立直、鸣牌、技能结算全部由 Python 服务端判定，客户端只负责画面与输入，不做任何规则推断。

---

## 下载

到 [**Releases**](https://github.com/Nanamichannel/chaonengli-mahjong/releases) 下载 **`Tianma.exe`**（约 189 MB，游戏资源已内嵌），**双击即玩**。

版本变化见 [**更新日志**](更新日志.md)（Releases 里每个版本也带一份）。

- **不用装任何东西，也不用写配置文件** —— 服务器地址已内置在客户端里（`server_net.gd` 的 `DEFAULT_URL`）
- 想连别的服务器 / 走单机：在 exe 同目录放一个 `net.cfg`，它会覆盖内置地址（格式见 `net.cfg.example`）
- 换皮肤：exe 同目录建 `skin/`，放同名 png（`bg.png` / `chi.png` / `rong.png` / `zimo.png` …），重启即生效

### 换房间（分桌打）

初始菜单**右上角**有「房間」输入框：填一个房间号 → 点「進入」，立刻换一张四人桌。

- 不同房间**完全隔离**：各自的 4 个座位、各自的牌局数据库
- 房间号支持中文 / 字母 / 数字，最长 24 字（`超能力`、`abc123` 都行）
- 留空 = 默认房间；选过的房间**本机会记住**（存 `user://room.txt`），下次启动直接进
- 每张桌固定 4 个座位，第 5 个人会被拒绝并提示「房间已满（4/4）」，有人退出后自动加入

---

## 特性

- **服务端权威**：所有判定在 `server/game.py`，客户端拿到的是「已算好的结果 + 可用动作列表」
- **46 张技能卡**：每张卡有专属交互（选牌 / 彩框描边选择 / 明牌展示 / 一对一对决 / 指定牌河……）
- **四窗联机**：HTTP + 租约（lease），也支持完全单机（客户端自动在本地拉起服务端子进程）
- **结算确认屏障**：四家都点「確認」后服务端才放行下一局
- **皮肤热替换**：把自己做的 png 丢进 exe 同目录的 `skin/`，重启即生效

---

## 目录结构

| 路径 | 说明 |
|---|---|
| `main.gd` | 客户端主控（场景、动作派发、UI 绘制） |
| `node_2d.tscn` | 牌桌场景（风盘 / 牌河 / 手牌 / 人物卡位） |
| `win_announce.gd` | 和了 / 流局播报面板（自绘，青玉配色） |
| `win_confirm_button.gd` | 结算确认按钮（自绘） |
| `identity_card*.gd` | 技能卡选卡界面 |
| `server/game.py` | 规则核心（配牌、摸打、鸣牌、和牌、技能） |
| `server/db.py` | SQLite 数据层 |
| `server/api_cli.py` | 操作派发（`OPS`） |
| `server/net_server.py` | HTTP 服务端 |
| `server/test_*.py` | 140+ 个服务端测试 |
| `Cailiao/` | 美术素材（牌图、UI、背景、技能卡） |
| `技术文档.md` / `代码索引.md` | 架构说明 / 函数位置索引 |

---

## 运行

### 客户端

1. 用 **Godot 4.7.2** 打开 `project.godot`
2. F5

### 服务端（联机）

```bash
cd server
python net_server.py
```

不写 `net.cfg` 时，客户端会在本机自动拉起服务端子进程（单机模式）。

### 联机配置

把 `net.cfg` 放在 **exe 同目录**（或 `user://net.cfg`），格式见 `net.cfg.example`：

```json
{ "url": "http://<服务端地址>:8000", "room": "default", "token": "", "timeout_ms": 10000 }
```

### 服务端测试

```bash
cd server
python test_game.py
python test_card05.py
python test_deal_skill.py
```

### 自己导出

```bash
# 预设名（export_presets.cfg 里的 name 字段）：天才麻将少女！
# binary_format/embed_pck=true → 产物只有一个 exe（资源内嵌），不用带 pck
godot --headless --path . --export-release "天才麻将少女！" build/Tianma.exe
```

---

## 素材与版权

- 麻将牌图来自 [lietxia/mahjong_graphic](https://github.com/lietxia/mahjong_graphic)（其 `LICENSE` 随目录保留）
- 其余人物立绘、字体等素材来自网络，**版权归各自原作者所有**
- 本项目仅用于学习交流，请勿商用；若权利人提出要求会及时移除相关素材

## 许可

代码部分采用 MIT License，见 [LICENSE](LICENSE)。
