extends Node

# ── 本窗口（客户端）的跨场景状态 ──────────────────────────────────
# 四个 Godot 实例 = 四个客户端，每个进程一份 ClientState。
# 座位号、大厅快照、四家最终卡序都放这里，换场景（菜单 → node_2d）不会丢。
# 注意：user:// 是四个实例共用的目录，所以「我这个窗口是几号位」不能写文件，
# 只能放进程内存（就是这里）。

var seat := -1                 # 0..3，-1 = 还没认领
var lobby: Dictionary = {}     # 服务端大厅快照（phase / seats / pool / turn）
var orders: Array = []         # 四家各自的 5 张最终顺序（进牌桌时从服务端抄下来）
var picks: Array = []
var room := ""               # 大厅里选的房间号（进牌桌时用同一个）          # 本家选到的 5 张（未排序）
