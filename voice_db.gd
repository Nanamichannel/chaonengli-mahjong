extends RefCounted

## 角色语音包（自动生成：Cailiao/Voice/音效/Saki-voice）
##
## 每个子文件夹 = 一个语音包；同一「种类」有多个文件时取**文件名最长**的那个
## （用户口径 2026-11-05，例如 takei_hisa 的 tsumo / tsumo2 → 用 tsumo2）。
## 种类：chi 吃 / pon 碰 / kan 杠 / reach 立直 / ron 荣和 / tsumo 自摸。

const ROOT := "res://Cailiao/Voice/音效/Saki-voice/"

const PACKS := {
	"amae_koromo": {"chi": "chi.wav", "pon": "pon.wav", "kan": "kan.wav", "reach": "reach2.wav", "ron": "ron.wav", "tsumo": "tsumo2.wav"},
	"bundo_seika": {"chi": "chi.wav", "pon": "pon.wav", "kan": "kan.wav", "reach": "reach_if_pass.wav", "ron": "ron.wav", "tsumo": "tsumo.wav"},
	"fujita_yasuko": {"chi": "chi.wav", "pon": "pon.wav", "kan": "kan.wav", "reach": "reach.wav", "ron": "ron.wav", "tsumo": "tsumo.wav"},
	"fukabori_sumio": {"chi": "chi.wav", "pon": "pon.wav", "kan": "kan.wav", "reach": "reach.wav", "ron": "ron.wav", "tsumo": "tsumo.wav"},
	"fukuji_mihoko": {"chi": "chi_desu.wav", "pon": "pon_desu.wav", "kan": "kan_desu.wav", "reach": "reach_desu.wav", "ron": "ron_desu.wav", "tsumo": "tsumo_desu.wav"},
	"haramora_nodoka": {"chi": "chi.wav", "pon": "pon.wav", "kan": "kan.wav", "reach": "reach.wav", "ron": "ron.wav", "tsumo": "tsumo.wav"},
	"ikeda_kana": {"chi": "chi.wav", "pon": "pon.wav", "kan": "kan.wav", "reach": "reach_v587.wav", "ron": "ron.wav", "tsumo": "tsumo.wav"},
	"inoue_jun": {"chi": "chi.wav", "pon": "pon.wav", "kan": "kan.wav", "reach": "reach.wav", "ron": "ron.wav", "tsumo": "tsumo.wav"},
	"kajiki_yumi": {"chi": "chi.wav", "pon": "pon.wav", "kan": "kan.wav", "reach": "reach.wav", "ron": "ron2.wav", "tsumo": "tsumo.wav"},
	"kanbara_satomi": {"chi": "chi.wav", "pon": "pon.wav", "kan": "kan.wav", "reach": "wahaha_reach.wav", "ron": "wahaha_ron.wav", "tsumo": "wahaha_tsumo.wav"},
	"kataoka_yuki": {"chi": "chi.wav", "pon": "pon.wav", "kan": "kan.wav", "reach": "reach2.wav", "ron": "ron.wav", "tsumo": "tsumo2.wav"},
	"kunihiro_hajime": {"chi": "chi.wav", "pon": "pon.wav", "kan": "kan.wav", "reach": "reach.wav", "ron": "ron.wav", "tsumo": "tsumo2.wav"},
	"miyanaga_saki": {"chi": "chi.wav", "pon": "pon.wav", "kan": "kan-w.wav", "reach": "reach.wav", "ron": "ron.wav", "tsumo": "tsumo2.wav"},
	"ryumonbuchi_toka": {"chi": "chi.wav", "pon": "pon.wav", "kan": "kan.wav", "reach": "reach_desuwa.wav", "ron": "ron_desuwa.wav", "tsumo": "irashaimashi_tsumo.wav"},
	"senoo_kaori": {"chi": "chi.wav", "pon": "pon.wav", "kan": "kan.wav", "reach": "reach.wav", "ron": "ron.wav", "tsumo": "tsumo.wav"},
	"someya_mako": {"chi": "chi.wav", "pon": "pon.wav", "kan": "kan.wav", "reach": "reach.wav", "ron": "ron.wav", "tsumo": "tsumo.wav"},
	"sugino_ayumi": {"chi": "chi.wav", "pon": "pon.wav", "kan": "kan.wav", "reach": "reach.wav", "ron": "ron.wav", "tsumo": "tsumo.wav"},
	"takei_hisa": {"chi": "chi.wav", "pon": "pon.wav", "kan": "kan.wav", "reach": "reach.wav", "ron": "ron.wav", "tsumo": "tsumo2.wav"},
	"touyoko_momoko": {"chi": "chi.wav", "pon": "pon.wav", "kan": "kan.wav", "reach": "reach.wav", "ron": "ron.wav", "tsumo": "tsumo.wav"},
	"tsuyama_mutsuki": {"chi": "chi.wav", "pon": "pon.wav", "kan": "kan.wav", "reach": "reach.wav", "ron": "ron.wav", "tsumo": "tsumo.wav"},
	"yoshitome_miharu": {"chi": "chi.wav", "pon": "pon.wav", "kan": "kan.wav", "reach": "reach.wav", "ron": "ron.wav", "tsumo": "tsumo.wav"},
	"yumeno_maho": {"chi": "chi.wav", "pon": "pon.wav", "kan": "kan.wav", "reach": "reach.wav", "ron": "ron.wav", "tsumo": "tsumo.wav"},
	"zawamura_tomoki": {"chi": "chi.wav", "pon": "pon.wav", "kan": "kan.wav", "reach": "reach.wav", "ron": "ron.wav", "tsumo": "tsumo.wav"},
}

const PACK_IDS: Array[String] = [
	"amae_koromo",
	"bundo_seika",
	"fujita_yasuko",
	"fukabori_sumio",
	"fukuji_mihoko",
	"haramora_nodoka",
	"ikeda_kana",
	"inoue_jun",
	"kajiki_yumi",
	"kanbara_satomi",
	"kataoka_yuki",
	"kunihiro_hajime",
	"miyanaga_saki",
	"ryumonbuchi_toka",
	"senoo_kaori",
	"someya_mako",
	"sugino_ayumi",
	"takei_hisa",
	"touyoko_momoko",
	"tsuyama_mutsuki",
	"yoshitome_miharu",
	"yumeno_maho",
	"zawamura_tomoki",
]


static func display_name(pack_id: String) -> String:
	var s := ""
	for w in pack_id.split("_", false):
		if s != "":
			s += " "
		s += w.substr(0, 1).to_upper() + w.substr(1)
	return s


static func kinds(pack_id: String) -> Dictionary:
	return PACKS.get(pack_id, {})


static func has_kind(pack_id: String, kind: String) -> bool:
	return PACKS.get(pack_id, {}).has(kind)


static func path_of(pack_id: String, kind: String) -> String:
	var m: Dictionary = PACKS.get(pack_id, {})
	var f := String(m.get(kind, ""))
	if f == "":
		return ""
	return ROOT + pack_id + "/" + f

