# 天才麻将少女 · 项目守则（自动注入，每轮都在）

`N:\apps\tianma` 是一个「**Godot 4.7 客户端 + Python/SQLite 服务端**」的日本麻将游戏。
客户端只画画面、发动作；**所有规则和所有数据都在 `server/`（Python）**。

## 开工前必读（按需读，不要整读）

| 文件 | 什么时候读 |
|---|---|
| **`交接_2026-10-20.md`** | **先读这个**：当前进度、未完成的 3 个 bug、下一步 |
| **`代码索引.md`** | 找函数位置：`grep -n "_c05_confirm" 代码索引.md` → 再 read 那几行 |
| `技术文档.md`（943 行） | 架构 / 目录 / 时序 / 踩坑。**按章节读**，别整读 |
| `server/README.md` | 数据库层设计 |

## 铁律

1. 规则只在服务端。客户端不自己判番、判吃碰。
2. `main.gd` **6858 行 / 262 KB**，`game.py` 2365 行，`node_2d.tscn` 224 KB。
   **禁止整文件读**：先 `grep '^func '` 拿行号，再 read 局部 50~150 行。
   （历史上 112 次 ≥1 MB 的工具返回，就是上下文被炸掉的主因。）
3. 改代码用「精确锚点 + `assert` 命中」的补丁脚本：写到 `N:\apps\_tmp\` 再 `python` 执行。
   不要按行号整段替换（会误删函数）。**中文锚点极易失配**（全角括号、「刚摸到」vs「刚摸的」）——
   优先用 ASCII 锚点或行号定位。
4. 临时脚本 / 测试库一律放 `N:\apps\_tmp\`，**别放进工程目录**（Godot 会扫描并报奇怪的错）。
5. `srv_request()`（main.gd:291）会把服务端拒绝吞成 `{}`，真实原因只在 `srv_note`。
   「点了没反应」先看 `srv_note`，别猜。
6. MCP 的 `evaluate_runtime_expression` 会超时，但**动作可能已经执行**。
   超时后先查 DB / `state`，不要盲目重发（会重复执行）。
7. 服务端测试：`cd N:\apps\tianma\server; python test_xxx.py`（python 3.10.2 在 PATH）。
   改服务端后至少跑 `test_card05` / `test_card06` / `test_deal_skill` / `test_swap` / `test_game`。
8. 语法检查：
   `N:\apps\Godot_v4.7.2-stable_mono_win64\Godot_v4.7.2-stable_mono_win64.exe --headless --path N:\apps\tianma --check-only --script res://main.gd`
9. 编辑器里开着 `main.gd` 时，改完必须让编辑器重新加载，否则旧缓冲会把改动覆盖回去。
   ★ **别叫用户手点**（用户口径 2026-11-02）——用 MCP 自己刷：
   `execute_editor_script`: `load("res://main.gd").reload(true)` →
   `EditorInterface.edit_script(load("res://main.gd"))` →
   用 `EditorInterface.get_script_editor().get_current_script().source_code` 确认含新代码。
   （`reload_project()` 只重扫文件系统，脚本资源还是缓存，`has_method` 仍为 false。）
10. **每次改完都要导出 exe**（用户口径 2026-11-02）：
    - 编辑器里：MCP `run_export(preset="天才麻将少女！", mode="release")`（返回很大，只看 tail 的 `success`）；
    - 或命令行：
      `N:\apps\Godot_v4.7.2-stable_mono_win64\Godot_v4.7.2-stable_mono_win64.exe --headless --path N:\apps\tianma --export-release "天才麻将少女！" build\Tianma.exe`
    - 产物 `build/Tianma.exe`（约 200 MB），导出模板在 `%APPDATA%\Godot\export_templates\4.7.2.stable.mono`。
    - 服务端（`server/*.py`）不打包进 exe，改了服务端要重启服务端进程，不用重导。
    - `build/` 里**只留 `Tianma.exe`**：`export_presets.cfg` 的 `debug/export_console_wrapper=0`
      （以前会多生成一个 `Tianma.console.exe`）。
    - 导出报「重命名 Tianma.tmp 失败」= 游戏正开着占用 exe → 先把 `Tianma.exe` 改名为
      `Tianma_prev.exe` 再导，导完删掉它，别留一堆 exe。

11. **版本号一天最多前进一次**（用户口径 2026-11-02）：
    当天所有改动都并进「当天第一个版本」的 `更新日志.md` 小节里，不要再 v1.0.7 → 1.0.8 → 1.0.9 一节节往上堆。
    一天里改五轮，也只是把条目补进同一节（按主题分组：和牌播报 / 规则 / 界面 / 性能…）。
    只有在「新的一天第一笔改动」时才 `+1`。

## 上下文卫生（对你自己的要求）

- 单次工具输出控制在 ~200 行内；大文件先定位再读局部。
- **不要 dump 整个 `state`**（几百个字段）——用 python 挑 3~5 个字段打印。
- 测试/日志输出只看最后 20 行。
- 需要「整体认知」时，读交接文档，不要去翻历史。
