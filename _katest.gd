extends SceneTree
# 一次性测试：server_net 长连接复用是否生效（跑完自己删）

func _initialize() -> void:
	call_deferred("_run")


func _write_cfg(url: String, room: String) -> void:
	var f := FileAccess.open("user://net.cfg", FileAccess.WRITE)
	if f != null:
		f.store_string('{"url":"%s","room":"%s","timeout_ms":9000}' % [url, room])
		f.close()


func _bench(url: String, tag: String) -> void:
	_write_cfg(url, "ka_test")
	var n = load("res://server_net.gd").new()
	if not n.enabled:
		print("[T] ", tag, " 未启用：", n.last_error)
		return
	var times: Array = []
	for i in range(6):
		var t0 := Time.get_ticks_usec()
		var r: Dictionary = n.request({"op": "lobby_state", "seat": 0})
		var dt := float(Time.get_ticks_usec() - t0) / 1000.0
		times.append(dt)
		if i == 0 or i == 5:
			print("[T] %s req#%d ok=%s %.1f ms calls=%d" % [tag, i, r.get("ok"), dt, n.calls])
	# 空闲 3 秒再打一次：验证长连接是否被中间层掐掉、能不能自己重连
	OS.delay_msec(3000)
	var t1 := Time.get_ticks_usec()
	var r2: Dictionary = n.request({"op": "lobby_state", "seat": 0})
	var dt2 := float(Time.get_ticks_usec() - t1) / 1000.0
	print("[T] %s 空闲3秒后 ok=%s %.1f ms" % [tag, r2.get("ok"), dt2])
	var warm: Array = times.slice(1)
	var sum := 0.0
	for v in warm:
		sum += float(v)
	print("[T] %s 首次 %.1f ms / 复用平均 %.1f ms" % [tag, float(times[0]), sum / maxf(float(warm.size()), 1.0)])


func _run() -> void:
	_bench("http://127.0.0.1:8000", "本地http")
	_bench("https://desktop-an1ub6a.tail7ef5a6.ts.net", "Funnel https")
	DirAccess.remove_absolute(ProjectSettings.globalize_path("user://net.cfg"))
	print("[T] 已清理 user://net.cfg")
	quit()
