# 超能力麻将！

Godot 4.7 客户端 + Python/SQLite 服务端的**日本麻将（立直麻将）**，带「技能卡（超能力）」变体玩法。

> 项目代号 **Tianma**，取自「天才麻将少女」。
> 核心设计原则：**规则只在服务端**。番符计算、立直、鸣牌、技能结算全部由 Python 服务端判定，客户端只负责画面与输入，不做任何规则推断。

---

## 下载

到 [**Releases**](https://github.com/Nanamichannel/chaonengli-mahjong/releases) 下载：

| 文件 | 说明 |
|---|---|
| `Tianma.exe` | 客户端（Windows x86_64） |
| `Tianma.pck` | 游戏资源，**必须和 exe 放在同一目录** |

可选：

- `net.cfg` —— 联机用，放 exe 同目录（格式见 `net.cfg.example`）
- `skin/` —— 换图目录，把同名 png 丢进去重启即生效，不用重新导出

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
godot --headless --path . --export-release "天才麻将少女！" build/Tianma.exe
```

导出后把 `Tianma.exe` + `Tianma.pck` + `net.cfg` + `skin/` 一起打包发给朋友即可。

---

## 素材与版权

- 麻将牌图来自 [lietxia/mahjong_graphic](https://github.com/lietxia/mahjong_graphic)（其 `LICENSE` 随目录保留）
- 其余人物立绘、字体等素材来自网络，**版权归各自原作者所有**
- 本项目仅用于学习交流，请勿商用；若权利人提出要求会及时移除相关素材

## 许可

代码部分采用 MIT License，见 [LICENSE](LICENSE)。
