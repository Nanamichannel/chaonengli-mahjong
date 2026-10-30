extends SceneTree
# 按真实轮询节奏测长连接保持：间隙 0.6s / 1.5s / 3s / 10s

func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	var f := FileAccess.open("user://net.cfg", FileAccess.WRITE)
	if f != null:
		f.store_string('{"url":"https://desktop-an1ub6a.tail7ef5a6.ts.net","room":"ka_test","timeout_ms":9000}')
		f.close()
	var n = load("res://server_net.gd").new()
	print("[T] enabled=", n.enabled)

	for gap in [0, 600, 1500, 3000, 10000]:
		var ts: Array = []
		for i in range(4):
			if gap > 0:
				OS.delay_msec(gap)
			var t0 := Time.get_ticks_usec()
			var r: Dictionary = n.request({"op": "lobby_state", "seat": 0})
			var dt := float(Time.get_ticks_usec() - t0) / 1000.0
			ts.append(dt)
			if not bool(r.get("ok", false)):
				print("[T] gap=%d req#%d 失败 %s" % [gap, i, r.get("error")])
		var s := ""
		for v in ts:
			s += "%.1f " % float(v)
		print("[T] gap=%5d ms -> %s" % [gap, s])

	DirAccess.remove_absolute(ProjectSettings.globalize_path("user://net.cfg"))
	print("[T] done")
	quit()
