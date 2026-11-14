# -*- coding: utf-8 -*-
# 客户端 ↔ 服务端的唯一通道
#
# 规矩：规则（和牌 / 听牌 / 振听 / 番符点）只在服务端 server/rules/*.py 里有一份，
#       客户端不再自己算 —— 客户端「把动作发上去」，把服务端回来的状态拿去显示。
#
# Godot 的 OS.execute 在 Windows 上读不到子进程 stdout，所以请求/响应都走文件：
#   写 user://srv_req.json → python server/api_cli.py --in … --out … → 读 user://srv_res.json
#
# 联机模式（server/net_server.py）：把同一份请求 POST 到 http 服务端。
#   有没有联机看 exe 同目录 / user:// 的 net.cfg（见 server_net.gd）。
#   没有 net.cfg → 走下面的本地子进程，行为完全不变。
class_name ServerBridge
extends RefCounted

const CLI := "res://server/api_cli.py"
# ★ 每个窗口（进程）用自己的一对文件。
#   user:// 是「整个项目」共用的一个目录 —— 四个窗口同时跑的时候，
#   如果都去写同一个 srv_req.json / srv_res.json，请求和响应就会互相抢：
#   我写的请求被别家覆盖、我去读的响应是别家的 → 座位认错、手牌串台、状态不同步。
const REQ_PREFIX := "user://srv_req_"
const RES_PREFIX := "user://srv_res_"

const NET_SCRIPT := preload("res://server_net.gd")
var net = null                           # 联机通道（net.cfg 存在时启用）
var python := ""
var available := false
var last_error := ""
var calls := 0
var req_path := ""                       # 本窗口专属（带进程号）
var res_path := ""

func _init() -> void:
	net = NET_SCRIPT.new()
	if net.enabled:
		available = true
		python = ""
		return                               # 联机模式：不找 python、不起子进程
	python = _find_python()
	available = python != ""
	# 进程号 = 一个窗口一个号，四个实例也不会撞
	var tag := str(OS.get_process_id())
	req_path = REQ_PREFIX + tag + ".json"
	res_path = RES_PREFIX + tag + ".json"
	if not available:
		last_error = "找不到 python（规则引擎跑不起来）"


# 规则脚本的位置。
# 编辑器里是 res://server/api_cli.py；导出成 exe 后这个路径在 pck 里面，
# Python 根本打不开 —— 这时退回到「exe 同目录/server/api_cli.py」。
# 所以：想让人拿 exe 也能单机打，就把 server 文件夹拷到 exe 旁边。
func _cli_path() -> String:
	var p := ProjectSettings.globalize_path(CLI)
	if FileAccess.file_exists(p):
		return p
	var alt := OS.get_executable_path().get_base_dir().path_join("server/api_cli.py")
	if FileAccess.file_exists(alt):
		return alt
	return p


static func _find_python() -> String:
	for name in ["python", "python3", "py"]:
		var probe := PackedStringArray()
		if OS.execute(name, PackedStringArray(["--version"]), probe, true) == 0:
			return name
	return ""


# 发一个请求，拿回服务端的响应。
# 注意：OS.execute 是阻塞的，一次调用会卡住主线程 0.1~0.3 秒，所以只用来问「判定」，
# 不要每帧都问。
# 对外入口：偶尔服务端正忙（四个窗口同时启动时抢写锁）会「没回话」，
# 这种情况自动重试，别让界面直接卡在「连不上服务端」。
# ── 联机时的「非阻塞轮询」：发出去就返回，主线程每帧推一点（见 server_net.gd）──
#   单机（本地 python 子进程）没有网络延迟，不需要这套 → 一律返回 false，调用方走同步。
func bg_ok() -> bool:
	# 联机：HTTP 流式；单机：起 python 子进程 + 轮询输出文件（也不阻塞主线程）
	return (net != null and bool(net.enabled)) or available


func bg_busy() -> bool:
	if net != null and bool(net.enabled):
		return bool(net.bg_busy())
	return _local_pid != 0


func bg_send(req: Dictionary) -> bool:
	req = _with_account(req)
	if net != null and bool(net.enabled):
		return bool(net.bg_send(req))
	return _local_bg_send(req)


func bg_poll() -> Dictionary:
	if net != null and bool(net.enabled):
		return net.bg_poll()
	return _local_bg_poll()


# ── 单机非阻塞通道 ────────────────────────────────────────────────────
# 主线程只做「写请求文件 / 起进程 / 每帧查输出文件」，python 跑在独立进程里。
# 以前 _poll() 每 0.35s 同步 OS.execute 一次（实测 94~105ms），界面一顿一顿。
var _local_pid := 0
var _local_deadline := 0
var _local_seq := 0
var _local_req := ""
var _local_res := ""


# 房间号 → 单机数据库路径：data/rooms/<房间号>.db
# （联机是服务端按 /rpc/<房间号> 分库；单机以前所有房间共用一个 mahjong.db，
#   于是「换房间」其实还是同一张桌子，残留的人机/昵称都会跟着。）
func _local_db_path() -> String:
	var r := ""
	if net != null:
		r = String(net.room).strip_edges()
	if r == "" or r == "default":
		return ""
	var safe := ""
	for i in range(r.length()):
		var ch := r.unicode_at(i)
		var ok := (ch >= 48 and ch <= 57) or (ch >= 65 and ch <= 90) \
			or (ch >= 97 and ch <= 122) or ch == 45 or ch == 95 \
			or (ch >= 0x4E00 and ch <= 0x9FFF)
		safe += (r[i] if ok else "_")
	if safe == "":
		return ""
	var dir := _cli_path().get_base_dir().path_join("data").path_join("rooms")
	DirAccess.make_dir_recursive_absolute(dir)
	return dir.path_join(safe + ".db")


func _local_bg_send(req: Dictionary) -> bool:
	if not available or _local_pid != 0:
		return false
	if not req.has("pid"):
		req = req.duplicate()
		req["pid"] = OS.get_process_id()
	_local_seq += 1
	var tag := "%d_%d" % [OS.get_process_id(), _local_seq]
	_local_req = "user://srv_bg_req_%s.json" % tag
	_local_res = "user://srv_bg_res_%s.json" % tag
	var req_abs := ProjectSettings.globalize_path(_local_req)
	var res_abs := ProjectSettings.globalize_path(_local_res)
	var f := FileAccess.open(_local_req, FileAccess.WRITE)
	if f == null:
		last_error = "请求文件写不了：" + req_abs
		return false
	f.store_string(JSON.stringify(req))
	f.close()
	if FileAccess.file_exists(_local_res):
		DirAccess.remove_absolute(res_abs)
	var args := PackedStringArray([_cli_path(), "--in", req_abs, "--out", res_abs])
	var dbp := _local_db_path()
	if dbp != "":
		args.append_array(PackedStringArray(["--db", dbp]))
	_local_pid = OS.create_process(python, args)
	calls += 1
	if _local_pid <= 0:
		_local_pid = 0
		last_error = "起不了 python 子进程"
		return false
	_local_deadline = Time.get_ticks_msec() + 5000
	return true


func _local_bg_poll() -> Dictionary:
	if _local_pid == 0:
		return {}
	var timeout := Time.get_ticks_msec() > _local_deadline
	var text := ""
	if FileAccess.file_exists(_local_res):
		var rf := FileAccess.open(_local_res, FileAccess.READ)
		if rf != null:
			text = rf.get_as_text()
			rf.close()
	if text.strip_edges() == "":
		if not timeout:
			return {}
		if OS.is_process_running(_local_pid):
			OS.kill(_local_pid)
		_local_bg_reset()
		last_error = "服务端没回话（单机）"
		return {}
	var data = JSON.parse_string(text)
	if typeof(data) != TYPE_DICTIONARY:
		if not timeout:
			return {}                       # 文件可能还没写完
		_local_bg_reset()
		last_error = "返回的不是 JSON"
		return {}
	_local_bg_reset()
	last_error = ""
	return data


func _local_bg_reset() -> void:
	if _local_req != "" and FileAccess.file_exists(_local_req):
		DirAccess.remove_absolute(ProjectSettings.globalize_path(_local_req))
	if _local_res != "" and FileAccess.file_exists(_local_res):
		DirAccess.remove_absolute(ProjectSettings.globalize_path(_local_res))
	_local_pid = 0
	_local_req = ""
	_local_res = ""


# ── 长连接推送（联机才有；单机返回 false / 空串）──
func push_ok() -> bool:
	return bg_ok() and bool(net.push_ok())


func push_tick() -> Dictionary:
	if not bg_ok():
		return {}
	return net.push_tick()


func push_set_seat(s: int) -> void:
	if net != null:
		net.push_set_seat(int(s))


func push_close() -> void:
	if net != null:
		net.push_close()


# 给请求补上「当前登录账号」：服务端据此把 seat ↔ 账号记下来（每小局记账要用）。
# 登录态在 ClientState（四个窗口共用一份 user://，所以「我是谁」不能写文件里）。
func _with_account(req: Dictionary) -> Dictionary:
	if req.has("account"):
		return req
	var nm := ""
	var tree := Engine.get_main_loop() as SceneTree
	if tree != null and tree.root != null:
		var cs := tree.root.get_node_or_null("ClientState")
		if cs != null:
			nm = String(cs.get("account"))
	if nm == "":
		return req
	req = req.duplicate()
	req["account"] = nm
	return req


func request(req: Dictionary) -> Dictionary:
	req = _with_account(req)
	if net != null and net.enabled:
		var rn: Dictionary = net.request(req)
		if not bool(rn.get("ok", false)) and String(rn.get("error", "")) != "":
			last_error = String(rn.get("error", ""))
		return rn
	var out: Dictionary = {}
	for attempt in range(3):
		out = _request_once(req)
		if not bool(out.get("__retry", false)):
			out.erase("__retry")
			return out
		OS.delay_msec(150)
	out.erase("__retry")
	return out


func _request_once(req: Dictionary) -> Dictionary:
	if not available:
		return {"ok": false, "error": last_error}
	# 带上进程号：服务端据此判断「这个座位对应的窗口还在不在」。
	# 编辑器点停止 / 强杀进程时不会有任何通知，只能靠进程还在不在来判断。
	if not req.has("pid"):
		req = req.duplicate()
		req["pid"] = OS.get_process_id()
	var req_abs := ProjectSettings.globalize_path(req_path)
	var res_abs := ProjectSettings.globalize_path(res_path)
	var f := FileAccess.open(req_path, FileAccess.WRITE)
	if f == null:
		last_error = "请求文件写不了：" + req_abs
		return {"ok": false, "error": last_error}
	f.store_string(JSON.stringify(req))
	f.close()
	if FileAccess.file_exists(res_path):
		DirAccess.remove_absolute(res_abs)      # 先把上一次的响应清掉，免得读到旧的

	var args := PackedStringArray([_cli_path(), "--in", req_abs,
		"--out", res_abs])
	var dbp2 := _local_db_path()
	if dbp2 != "":
		args.append_array(PackedStringArray(["--db", dbp2]))
	var lines := PackedStringArray()
	var code := OS.execute(python, args, lines, true)
	calls += 1

	var text := ""
	if FileAccess.file_exists(res_path):
		var rf := FileAccess.open(res_path, FileAccess.READ)
		if rf != null:
			text = rf.get_as_text()
			rf.close()
	if text.strip_edges() == "":
		text = "\n".join(lines)
	if text.strip_edges() == "":
		last_error = "服务端没回话（退出码 %d）" % code
		# ★ 只有 python 自己出错（退出码非 0）才重试：那种情况动作肯定没执行。
		#   退出码 0 却没响应 = 动作可能已经做了，重发会变成「重复动作」（比如多打一张牌）。
		return {"ok": false, "error": last_error, "__retry": code != 0}
	var data = JSON.parse_string(text)
	if typeof(data) != TYPE_DICTIONARY:
		last_error = "返回的不是 JSON：" + text.substr(0, 120)
		return {"ok": false, "error": last_error}
	last_error = ""
	return data
