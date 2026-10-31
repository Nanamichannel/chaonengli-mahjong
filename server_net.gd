# -*- coding: utf-8 -*-
# 客户端 ↔ 服务端：**联机模式**的通道
#
# 单机（默认）走 ServerBridge：本机起一个 python 子进程，用文件传请求。
# 联机走这里：把同一份请求 JSON POST 到 server/net_server.py，拿回同一份响应。
#
# 配置文件（JSON，两处任选；先找到的生效）：
#   ① 游戏 exe 同目录的 net.cfg      ← 发给朋友时把它和 exe 放一起
#   ② user://net.cfg                 ← 本机调试用
#
#   {
#     "url":   "http://192.168.1.10:8000",   // 服务端地址（结尾不要带 /rpc）
#     "room":  "default",                    // 房间号（服务端没配过会自动建）
#     "token": "",                           // 服务端要求就填，留空不校验
#     "timeout_ms": 10000                    // 可选，单次请求最长等多久
#   }
#
# 没有 net.cfg → enabled=false，客户端自动退回单机模式（编辑器 / 单机测试不受影响）。
extends RefCounted

const CFG_EXE := "net.cfg"
const CFG_USER := "user://net.cfg"
# 本机记住玩家选的房间号（初始菜单里改），优先级高于 net.cfg 的 room
const ROOM_MEMO := "user://room.txt"
# 内置默认服务器：导出版「双击就联机」，朋友不用写 net.cfg。
#   · 编辑器里不生效（OS.has_feature("template") == false）→ 单机调试不受影响
#   · exe 同目录放 net.cfg 会覆盖这里（想连别的服务器/单机就放一个）
const DEFAULT_URL := "https://desktop-an1ub6a.tail7ef5a6.ts.net"

var enabled := false
var url := ""
var room := "default"
var token := ""
var timeout_ms := 10000
var last_error := ""
var calls := 0
# ★ 长连接复用：原来每次请求都 new HTTPClient + connect + TLS 握手，
#   实测 Funnel 下这一次握手要 42 ms（46.7 → 4.5）。改成复用同一条连接。
# ★ 连不上服务端时，**绝不能**把主线程按在 TCP 连接里 —— 那会让窗口变成
#   「未响应」，玩家看到的就是「一打开就卡死」。
#   单次建连接最多等 CONNECT_MS；失败后 DOWN_MS 之内 request() 直接回错误，
#   一次都不去碰网络（主线程这段时间完全自由）。连上就清零。
const CONNECT_MS := 900
const DOWN_MS := 3000
var _down_until := 0                 # Time.get_ticks_msec() 之前不再尝试连接
var _http: HTTPClient = null
var _retry_safe := false      # 本次失败能不能安全重发（只有「还没发出去」才算安全）

var _host := ""
var _port := 80
var _tls := false
var _base_path := ""

func _init() -> void:
	_load_cfg()

func _load_cfg() -> void:
	var txt := ""
	var exe_dir := OS.get_executable_path().get_base_dir()
	for p in [exe_dir.path_join(CFG_EXE), CFG_USER]:
		if str(p) == "" or not FileAccess.file_exists(str(p)):
			continue
		var f := FileAccess.open(str(p), FileAccess.READ)
		if f != null:
			txt = f.get_as_text()
			f.close()
		if txt.strip_edges() != "":
			break
	if txt.strip_edges() == "":
		if DEFAULT_URL == "" or not OS.has_feature("template"):
			return                               # 没有配置文件（且无内置地址 / 在编辑器里）= 单机模式
		url = DEFAULT_URL
		room = "default"
		token = ""
		# ★ 这条以前直接 return，把「大厅选的房间号」整段跳过了 →
		#   大厅在 1145、进牌桌却连回 default（两家的卡序/遮罩完全不一样，
		#   桌面人物卡跟大厅选的对不上）。现在两条路都走同一个房间解析。
		_apply_room_memo()
		enabled = _parse_url()
		if enabled:
			print("[net] 联机模式（内置地址）：%s  房间=%s" % [url, room])
		else:
			last_error = "内置地址认不出来：%s" % url
			push_warning("[net] " + last_error)
		return
	var d = JSON.parse_string(txt)
	if typeof(d) != TYPE_DICTIONARY:
		last_error = "net.cfg 不是合法 JSON"
		return
	var dd := d as Dictionary
	url = String(dd.get("url", "")).strip_edges()
	if url == "":
		return
	room = String(dd.get("room", "default")).strip_edges()
	if room == "":
		room = "default"
	token = String(dd.get("token", ""))
	timeout_ms = int(dd.get("timeout_ms", timeout_ms))
	if timeout_ms < 1000:
		timeout_ms = 1000
	# 玩家在初始菜单里选过的房间号（本机记忆 / 大厅记忆）优先级最高
	_apply_room_memo()
	enabled = _parse_url()
	if enabled:
		# 调试的时候一眼能看出来现在连的是谁
		print("[net] 联机模式：%s  房间=%s" % [url, room])
	else:
		last_error = "net.cfg 里的 url 认不出来：%s" % url
		push_warning("[net] " + last_error)

# http://host:port/prefix → _tls/_host/_port/_base_path
func _parse_url() -> bool:
	var u := url
	_tls = false
	if u.begins_with("https://"):
		_tls = true
		u = u.substr(8)
	elif u.begins_with("http://"):
		u = u.substr(7)
	else:
		return false
	var slash := u.find("/")
	if slash >= 0:
		_base_path = u.substr(slash)
		u = u.substr(0, slash)
	while _base_path.ends_with("/"):
		_base_path = _base_path.substr(0, _base_path.length() - 1)
	var colon := u.find(":")
	if colon >= 0:
		_host = u.substr(0, colon)
		_port = int(u.substr(colon + 1))
	else:
		_host = u
		_port = 443 if _tls else 80
	return _host != "" and _port > 0


# ── 房间号的三个来源：配置文件 < user://room.txt < ClientState.room（大厅里选的，进牌桌也要认）──
#   以前这段只在「有 net.cfg」的分支里跑，导出版（内置地址）直接跳过 →
#   大厅 1145 / 牌桌 default 的事故。现在两条分支都调它。
func _apply_room_memo() -> void:
	var memo := _read_room_memo()
	if memo != "" and room_ok(memo):
		room = memo
	var cs := _client_state()
	if cs != null:
		var v = cs.get("room")
		if v != null:
			var r2 := String(v).strip_edges()
			if r2 != "" and room_ok(r2):
				room = r2


func _read_room_memo() -> String:
	if not FileAccess.file_exists(ROOM_MEMO):
		return ""
	var rf := FileAccess.open(ROOM_MEMO, FileAccess.READ)
	if rf == null:
		return ""
	var memo := rf.get_as_text().strip_edges()
	rf.close()
	return memo


func _client_state() -> Node:
	var tree := Engine.get_main_loop() as SceneTree
	if tree == null or tree.root == null:
		return null
	return tree.root.get_node_or_null("ClientState")


# ── 房间号（运行时切换用）───────────────────────────────────────────
# 房间号只做「一张四人桌」的隔离键：服务端按 /rpc/<房间号> 建独立库、独立 4 个座位。
# 玩家在初始菜单里选的房间会记进 user://room.txt（本机记忆，优先级高于 net.cfg 的 room），
# 这样既不用改 net.cfg，也不会把 exe 目录里的配置写脏。
# （常量 ROOM_MEMO 定义在文件顶部）


# 房间号会直接拼进 URL 路径，只放行字母/数字/-/_/中文，别的一律拒。
func room_ok(r: String) -> bool:
	if r == "" or r.length() > 24:
		return false
	for i in range(r.length()):
		var ch := r.unicode_at(i)
		var pass_ch := (ch >= 0x30 and ch <= 0x39) \
			or (ch >= 0x41 and ch <= 0x5A) \
			or (ch >= 0x61 and ch <= 0x7A) \
			or ch == 0x2D or ch == 0x5F \
			or (ch >= 0x4E00 and ch <= 0x9FFF)
		if not pass_ch:
			return false
	return true


func set_room(r: String) -> bool:
	var want := r.strip_edges()
	if want == "":
		want = "default"
	if not room_ok(want):
		return false
	room = want
	# 记到 ClientState：换场景（菜单 → 牌桌）后新建的 ServerBridge 也能拿到同一个房间号
	var cs := _client_state()
	if cs != null:
		cs.set("room", want)
	var f := FileAccess.open(ROOM_MEMO, FileAccess.WRITE)
	if f != null:
		f.store_string(want)
		f.close()
	if enabled:
		print("[net] 换房间：%s" % room)
	return true


# 对外唯一入口：和 ServerBridge.request() 同一个契约（成功 → 服务端那份 JSON）
#   ★ 不带 pid：服务端的座位租约靠「多久没发请求」判断（12 秒），
#     进程号在别的机器上毫无意义，带上反而会被当成「窗口已经关了」。
func request(req: Dictionary) -> Dictionary:
	if not enabled:
		return {"ok": false, "error": last_error}
	if Time.get_ticks_msec() < _down_until:
		# 刚确认连不上 → 这一小段别再阻塞主线程，立刻把错误还回去
		if last_error == "":
			last_error = "连不上服务端（%s:%d）" % [_host, _port]
		return {"ok": false, "error": last_error}
	# 有非阻塞轮询在飞 → 先把它收干净（同一个 keep-alive 连接不能并发）
	if _bg_state != 0:
		_bg_drain()
	var r := _post(req)
	# 长连接可能被中间层悄悄掐断：这种「请求根本没发出去」的情况可以安全重来一次。
	# （一旦 request() 已经返回 OK，动作就可能已经执行了，绝不能重发 —— 会重复打牌。）
	if r.is_empty() and _retry_safe:
		_reset_conn()
		r = _post(req)
	if r.is_empty():
		return {"ok": false, "error": last_error}
	last_error = ""
	_down_until = 0
	calls += 1
	return r

func _reset_conn() -> void:
	if _http != null:
		_http.close()
	_http = null


# 复用已有连接；状态不对（被掐断 / 从没连过）就重连一次。
func _ensure_connected() -> bool:
	if _http != null:
		if _http.get_status() == HTTPClient.STATUS_CONNECTED:
			return true
		_http.poll()                       # 空闲时状态不会自己更新，poll 一下让断连暴露出来
		if _http.get_status() == HTTPClient.STATUS_CONNECTED:
			return true
		_reset_conn()
	if Time.get_ticks_msec() < _down_until:
		return false                       # 掉线窗口内：不碰网络，让主线程喘口气
	var http := HTTPClient.new()
	var tls_opt: TLSOptions = null
	if _tls:
		tls_opt = TLSOptions.client()
	var err := http.connect_to_host(_host, _port, tls_opt)
	if err != OK:
		last_error = "连不上 %s:%d（错误码 %d）" % [_host, _port, err]
		_down_until = Time.get_ticks_msec() + DOWN_MS
		return false
	# ★ 这里原来用 timeout_ms（10 秒）：主机不可达时窗口会整段「未响应」。
	#   建连接只给 CONNECT_MS，连不上就迅速退回、过 DOWN_MS 再试。
	var deadline := Time.get_ticks_msec() + mini(timeout_ms, CONNECT_MS)
	while http.get_status() in [HTTPClient.STATUS_RESOLVING, HTTPClient.STATUS_CONNECTING]:
		http.poll()
		if Time.get_ticks_msec() > deadline:
			last_error = "连不上服务端 %s:%d（连接超时）" % [_host, _port]
			http.close()
			_down_until = Time.get_ticks_msec() + DOWN_MS
			return false
		OS.delay_msec(2)
	if http.get_status() != HTTPClient.STATUS_CONNECTED:
		last_error = "连不上服务端 %s:%d（状态 %d）" % [_host, _port, http.get_status()]
		http.close()
		_down_until = Time.get_ticks_msec() + DOWN_MS
		return false
	_http = http
	_down_until = 0
	return true

func _post(req: Dictionary) -> Dictionary:
	var body := JSON.stringify(req)
	var path := "/rpc/" + room.uri_encode()
	if token != "":
		path += "?token=" + token.uri_encode()
	var deadline := Time.get_ticks_msec() + timeout_ms

	if not _ensure_connected():
		_retry_safe = true                 # 连接都没建起来，动作肯定没执行
		return {}
	var http := _http

	# ★ Connection: keep-alive —— 服务端是 HTTP/1.1 + 带 Content-Length，支持复用
	var headers := PackedStringArray([
		"Content-Type: application/json",
		"Accept: application/json",
		"Connection: keep-alive",
		"User-Agent: TianmaGodot/1.0",
	])
	var err := http.request(HTTPClient.METHOD_POST, _base_path + path, headers, body)
	if err != OK:
		last_error = "发不出去（错误码 %d）" % err
		_retry_safe = true
		_reset_conn()
		return {}

	# ↓ 从这里开始请求已经离开本机，失败一律不重发（可能已经执行）
	_retry_safe = false

	while http.get_status() == HTTPClient.STATUS_REQUESTING:
		http.poll()
		if Time.get_ticks_msec() > deadline:
			last_error = "等响应超时（%d ms）" % timeout_ms
			_reset_conn()
			return {}
		OS.delay_msec(2)
	if not http.has_response():
		last_error = "服务端没有响应（状态 %d）" % http.get_status()
		_reset_conn()
		return {}

	var code := http.get_response_code()
	var raw := PackedByteArray()
	while http.get_status() == HTTPClient.STATUS_BODY:
		http.poll()
		var chunk := http.read_response_body_chunk()
		if chunk.size() > 0:
			raw += chunk
		else:
			OS.delay_msec(2)
		if Time.get_ticks_msec() > deadline:
			last_error = "读响应超时（%d ms）" % timeout_ms
			_reset_conn()
			return {}

	# 读完不主动 close：状态回到 CONNECTED 就留着下次用，断了就丢掉
	if http.get_status() != HTTPClient.STATUS_CONNECTED:
		_reset_conn()

	var text := raw.get_string_from_utf8()
	var data = JSON.parse_string(text)
	if typeof(data) != TYPE_DICTIONARY:
		last_error = "返回的不是 JSON（HTTP %d）：%s" % [code, text.substr(0, 120)]
		return {}
	if code != 200 and not (data as Dictionary).has("ok"):
		last_error = "HTTP %d" % code
		return {}
	return data as Dictionary


# ── 非阻塞轮询（只给「定时问 state」用）──────────────────────────────
#   公网（Tailscale Funnel）往返 100~300ms，同步等待会把画面按住整段 RTT，
#   0.35s 问一次 = 每 0.35 秒掉一次帧。这里发出去就返回，_process 每帧推一点。
var _bg_state := 0                     # 0 空闲 / 1 等响应头 / 2 读 body
var _bg_deadline := 0
var _bg_raw := PackedByteArray()
var _bg_code := 0

func bg_busy() -> bool:
	return _bg_state != 0


func bg_send(req: Dictionary) -> bool:
	if not enabled or _bg_state != 0:
		return false
	if Time.get_ticks_msec() < _down_until:
		return false
	if not _ensure_connected():
		return false
	var body := JSON.stringify(req)
	var path := "/rpc/" + room.uri_encode()
	if token != "":
		path += "?token=" + token.uri_encode()
	var headers := PackedStringArray([
		"Content-Type: application/json",
		"Accept: application/json",
		"Connection: keep-alive",
		"User-Agent: TianmaGodot/1.0",
	])
	var err := _http.request(HTTPClient.METHOD_POST, _base_path + path, headers, body)
	if err != OK:
		last_error = "发不出去（错误码 %d）" % err
		_reset_conn()
		return false
	_bg_state = 1
	_bg_raw = PackedByteArray()
	_bg_code = 0
	_bg_deadline = Time.get_ticks_msec() + timeout_ms
	return true


# 每帧调一次：还没完回 {}，收完回服务端那份 JSON
func bg_poll() -> Dictionary:
	if _bg_state == 0:
		return {}
	var http := _http
	if http == null:
		_bg_state = 0
		return {}
	http.poll()
	if _bg_state == 1:
		if http.get_status() == HTTPClient.STATUS_REQUESTING:
			if Time.get_ticks_msec() > _bg_deadline:
				last_error = "等响应超时（%d ms）" % timeout_ms
				bg_reset()
			return {}
		if not http.has_response():
			if Time.get_ticks_msec() > _bg_deadline:
				last_error = "服务端没有响应（状态 %d）" % http.get_status()
				bg_reset()
			return {}
		_bg_code = http.get_response_code()
		_bg_state = 2
	# 只在 STATUS_BODY 时读；读完状态会自己跳走，硬读会刷 ERROR
	while http.get_status() == HTTPClient.STATUS_BODY:
		var chunk := http.read_response_body_chunk()
		if chunk.size() == 0:
			break
		_bg_raw += chunk
	if http.get_status() == HTTPClient.STATUS_BODY:
		if Time.get_ticks_msec() > _bg_deadline:
			last_error = "读响应超时（%d ms）" % timeout_ms
			bg_reset()
		return {}
	_bg_state = 0
	if http.get_status() != HTTPClient.STATUS_CONNECTED:
		_reset_conn()
	_down_until = 0
	last_error = ""
	calls += 1
	var text := _bg_raw.get_string_from_utf8()
	var data = JSON.parse_string(text)
	if typeof(data) != TYPE_DICTIONARY:
		last_error = "返回的不是 JSON（HTTP %d）：%s" % [_bg_code, text.substr(0, 120)]
		return {}
	if _bg_code != 200 and not (data as Dictionary).has("ok"):
		last_error = "HTTP %d" % _bg_code
		return {}
	return data as Dictionary


func bg_reset() -> void:
	if _bg_state != 0:
		_reset_conn()
	_bg_state = 0


# 主线程要发真正的动作 → 把在飞的轮询收干净（最多等 timeout_ms，通常只差几十毫秒）
func _bg_drain() -> void:
	var guard := Time.get_ticks_msec() + mini(timeout_ms, 1500)
	while _bg_state != 0:
		bg_poll()
		if Time.get_ticks_msec() > guard:
			last_error = "轮询没有响应，放弃这一次"
			bg_reset()
			return
		OS.delay_msec(1)


# 现在是不是「刚确认连不上」的冷却期（界面据此显示提示、别再催）
func offline() -> bool:
	return Time.get_ticks_msec() < _down_until


# 给界面显示用的一句话
func status_text() -> String:
	if not enabled:
		return "单机模式"
	return "联机：%s（房间 %s）" % [url, room]
