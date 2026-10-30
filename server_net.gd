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


# 对外唯一入口：和 ServerBridge.request() 同一个契约（成功 → 服务端那份 JSON）
#   ★ 不带 pid：服务端的座位租约靠「多久没发请求」判断（12 秒），
#     进程号在别的机器上毫无意义，带上反而会被当成「窗口已经关了」。
func request(req: Dictionary) -> Dictionary:
	if not enabled:
		return {"ok": false, "error": last_error}
	var r := _post(req)
	if r.is_empty():
		return {"ok": false, "error": last_error}
	last_error = ""
	calls += 1
	return r

func _post(req: Dictionary) -> Dictionary:
	var body := JSON.stringify(req)
	var path := "/rpc/" + room
	if token != "":
		path += "?token=" + token.uri_encode()
	var deadline := Time.get_ticks_msec() + timeout_ms

	var http := HTTPClient.new()
	var tls_opt: TLSOptions = null
	if _tls:
		tls_opt = TLSOptions.client()
	var err := http.connect_to_host(_host, _port, tls_opt)
	if err != OK:
		last_error = "连不上 %s:%d（错误码 %d）" % [_host, _port, err]
		return {}
	while http.get_status() in [HTTPClient.STATUS_RESOLVING, HTTPClient.STATUS_CONNECTING]:
		http.poll()
		if Time.get_ticks_msec() > deadline:
			last_error = "连接超时：%s:%d" % [_host, _port]
			return {}
		OS.delay_msec(2)
	if http.get_status() != HTTPClient.STATUS_CONNECTED:
		last_error = "连接失败（状态 %d）：%s:%d" % [http.get_status(), _host, _port]
		return {}

	var headers := PackedStringArray([
		"Content-Type: application/json",
		"Accept: application/json",
		"Connection: close",
		"User-Agent: TianmaGodot/1.0",
	])
	err = http.request(HTTPClient.METHOD_POST, _base_path + path, headers, body)
	if err != OK:
		last_error = "发不出去（错误码 %d）" % err
		return {}
	while http.get_status() == HTTPClient.STATUS_REQUESTING:
		http.poll()
		if Time.get_ticks_msec() > deadline:
			last_error = "等响应超时（%d ms）" % timeout_ms
			return {}
		OS.delay_msec(2)
	if not http.has_response():
		last_error = "服务端没有响应（状态 %d）" % http.get_status()
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
			return {}
	http.close()

	var text := raw.get_string_from_utf8()
	var data = JSON.parse_string(text)
	if typeof(data) != TYPE_DICTIONARY:
		last_error = "返回的不是 JSON（HTTP %d）：%s" % [code, text.substr(0, 120)]
		return {}
	if code != 200 and not (data as Dictionary).has("ok"):
		last_error = "HTTP %d" % code
		return {}
	return data as Dictionary


# 给界面显示用的一句话
func status_text() -> String:
	if not enabled:
		return "单机模式"
	return "联机：%s（房间 %s）" % [url, room]
