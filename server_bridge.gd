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
# ★ 2026-11-15：单机常驻服务端（见 server/api_worker.py）
#   以前每个请求起一个新 python ≈ 101ms → 点一张牌冻 100ms（「切牌非常卡」）。
#   常驻进程里 handle() 往返实测 2~4ms，且不再阻塞主线程。
var _wk := {}                             # db_key -> {pid, req, res, db}
var _wk_seq := 0                          # 请求序号（服务端据此判重）
var _wk_fail := 0                         # 连失败两次就永久关掉，退回一次性子进程
var _wk_bg := {}                          # 非阻塞通道里「还没收」的那一发
var _wk_lost := {}                        # 同步请求插队时收掉的、还没交给调用方的那一份
var res_path := ""

func _init() -> void:
	net = NET_SCRIPT.new()
	if net.enabled:
		available = true
		python = ""
		return                               # 联机模式：不找 python、不起子进程
	# ★ 安卓/iOS 起不了 python 子进程：不要静默「单机」，否则玩家看到的是点了没反应。
	#   直接标记不可用，由上层弹出「需要联网」的提示（2026-11-15 安卓移植）。
	if OS.has_feature("mobile"):
		python = ""
		available = false
		last_error = "移动端不支持单机模式，请检查网络后重试"
		return
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
	if not _wk_lost.is_empty():
		return true                       # 有一份收好了还没交出去
	if not _wk_bg.is_empty():
		return true                       # 常驻进程那一发还没收
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


# ── 单机常驻服务端（api_cli.py --serve）────────────────────────────────
# 协议：写请求文件（带递增 _seq）→ 常驻进程处理 → 原子替换响应文件（回带同一 _seq）。
# 客户端只读响应文件、拿 seq 对上号才算数，所以旧残留不会串包。
# 为什么不用管道：Godot 读管道会阻塞主线程，而这里是「非阻塞等 + 同步只等 2~4ms」。


# 取（必要时起）这个房间库的常驻进程
func _worker_for(db_path: String) -> Dictionary:
	if not available or python == "" or _wk_fail >= 2:
		return {}
	var key := db_path if db_path != "" else "default"
	var w = _wk.get(key, null)
	if w != null and int((w as Dictionary).get("pid", 0)) > 0 \
			and OS.is_process_running(int((w as Dictionary)["pid"])):
		return w
	var cli := _cli_path()
	if not FileAccess.file_exists(cli):
		_wk_fail = 99                       # 脚本都找不到 → 永久走一次性子进程
		return {}
	var tag := "%d_%d" % [OS.get_process_id(), _wk.size() + 1]
	var nw := {"pid": 0,
		"req": "user://srv_w_req_%s.json" % tag,
		"res": "user://srv_w_res_%s.json" % tag,
		"db": db_path}
	var args := PackedStringArray([cli, "--serve",
		"--in", ProjectSettings.globalize_path(String(nw["req"])),
		"--out", ProjectSettings.globalize_path(String(nw["res"])),
		"--idle", "900", "--parent", str(OS.get_process_id())])
	if db_path != "":
		args.append_array(PackedStringArray(["--db", db_path]))
	var pid := OS.create_process(python, args)
	if pid <= 0:
		_wk_fail += 1
		last_error = "起不了常驻服务端（改回一次性子进程）"
		return {}
	nw["pid"] = pid
	_wk[key] = nw
	return nw


func _worker_write(w: Dictionary, req: Dictionary) -> int:
	if w.is_empty():
		return 0
	if not _wk_bg.is_empty():
		_wk_bg = {}                       # 被这一发插队了：作废，别让它等满 5s 算失败
	_wk_seq += 1
	var r := req.duplicate()
	r["_seq"] = _wk_seq
	if not r.has("pid"):
		r["pid"] = OS.get_process_id()
	var f := FileAccess.open(String(w["req"]), FileAccess.WRITE)
	if f == null:
		last_error = "请求文件写不了：" + String(w["req"])
		return 0
	f.store_string(JSON.stringify(r))
	f.close()
	calls += 1
	return _wk_seq


# 非阻塞读：没回来（或 seq 对不上）就回空字典
func _worker_read(w: Dictionary, seq: int) -> Dictionary:
	if w.is_empty() or seq <= 0:
		return {}
	var p := String(w.get("res", ""))
	if p == "" or not FileAccess.file_exists(p):
		return {}
	var f := FileAccess.open(p, FileAccess.READ)
	if f == null:
		return {}
	var txt := f.get_as_text()
	f.close()
	if txt.strip_edges() == "":
		return {}
	var d = JSON.parse_string(txt)
	if typeof(d) != TYPE_DICTIONARY:
		return {}                          # 正在写 → 下一帧再看
	var dd: Dictionary = d
	if int(dd.get("_seq", -1)) != seq:
		return {}
	dd.erase("_seq")
	last_error = ""
	return dd


# 同步走常驻进程：正常 2~4ms 就回来（老办法 101ms）
func _worker_request(req: Dictionary, wait_ms := 2000) -> Dictionary:
	# 同步请求要插队 → 先把在飞的那一发收干净（别丢：异步动作的响应就是它）
	if not _wk_bg.is_empty():
		var d0 := _local_bg_poll()
		if not d0.is_empty():
			_wk_lost = d0
	var w := _worker_for(_local_db_path())
	if w.is_empty():
		return {}
	var seq := _worker_write(w, req)
	if seq <= 0:
		_wk_fail += 1
		return {}
	var deadline := Time.get_ticks_msec() + int(wait_ms)
	var pid := int(w.get("pid", 0))
	var spin := 0
	while true:
		var d := _worker_read(w, seq)
		if not d.is_empty():
			return d
		spin += 1
		if spin % 100 == 0 and pid > 0 and not OS.is_process_running(pid):
			_wk_fail += 1                 # 进程没了：别干等，立刻退回一次性子进程
			last_error = "常驻服务端进程没了（改回一次性子进程）"
			return {}
		if Time.get_ticks_msec() >= deadline:
			_wk_fail += 1
			last_error = "常驻服务端没回话（改回一次性子进程）"
			return {}
		OS.delay_msec(1)
	return {}


# 关窗口 / 停编辑器时把常驻进程收掉（不然会留下一个 python 僵尸）
func shutdown() -> void:
	for k in _wk.keys():
		var pid := int((_wk[k] as Dictionary).get("pid", 0))
		if pid > 0 and OS.is_process_running(pid):
			OS.kill(pid)
	_wk.clear()
	_wk_bg = {}
	if _local_pid != 0 and OS.is_process_running(_local_pid):
		OS.kill(_local_pid)
		_local_pid = 0


# ── 单机非阻塞通道（老办法：一次一个子进程）──────────────────────────
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
	if not available or _local_pid != 0 or not _wk_bg.is_empty():
		return false
	# ★ 优先常驻进程：只写请求文件，2~4ms 后由 _local_bg_poll 收结果
	var wk := _worker_for(_local_db_path())
	if not wk.is_empty():
		var wseq := _worker_write(wk, req)
		if wseq > 0:
			_wk_bg = {"key": String(wk["req"]), "seq": wseq,
				"deadline": Time.get_ticks_msec() + 5000}
			return true
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
	if not _wk_lost.is_empty():
		var d0 := _wk_lost
		_wk_lost = {}
		return d0
	if not _wk_bg.is_empty():
		var wk2 = _wk.get("default", null)
		for k2 in _wk.keys():
			if String((_wk[k2] as Dictionary).get("req", "")) == String(_wk_bg["key"]):
				wk2 = _wk[k2]
				break
		if wk2 != null:
			var d2 := _worker_read(wk2, int(_wk_bg["seq"]))
			if not d2.is_empty():
				_wk_bg = {}
				return d2
		if Time.get_ticks_msec() > int(_wk_bg.get("deadline", 0)):
			_wk_bg = {}
			_wk_fail += 1
			last_error = "常驻服务端没回话（改回一次性子进程）"
		return {}
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
	# ★ 单机：先走常驻进程（2~4ms）；起不来/没回话两次就永久退回一次性子进程
	var rw := _worker_request(req)
	if not rw.is_empty():
		return rw
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
