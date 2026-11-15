# -*- coding: utf-8 -*-
extends RefCounted
##
## txt.gd —— 显示层文本整形（把中文全角标点换成半角，手机上显得没那么大）
##
## 只用于**显示**：协议字段、比较用的字符串一律不要走这里。
## 用法：
##   const Txt := preload("res://txt.gd")
##   lbl.text = Txt.half(some_text)

const MAP := {
	"：": ":", "，": ",", "；": ";", "（": "(", "）": ")",
	"、": ",", "【": "[", "】": "]", "\u3000": " ", "＝": "=",
	"／": "/", "％": "%",
}

## 没有全角标点时原样返回（不额外分配字符串）
static func half(s: String) -> String:
	var need := false
	for k in MAP.keys():
		if s.contains(k):
			need = true
			break
	if not need:
		return s
	for k in MAP.keys():
		if s.contains(k):
			s = s.replace(k, MAP[k])
	return s
