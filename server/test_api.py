"""跑一遍客户端会用到的流程（调试用）：python _flow.py"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

import api_cli
from db import DB

DB_PATH = api_cli.DB_PATH


def show(tag, d, keys=("hand", "turn", "phase", "waits")):
    s = d.get("state") or {}
    print(f"--- {tag}: ok={d.get('ok')} err={d.get('error')}")
    if not s:
        return
    print("    " + "  ".join(f"{k}={s.get(k)}" for k in keys))
    print("    legal =", [a.get("action") for a in s.get("legal", [])])
    t = s.get("tenpai") or {}
    print(f"    tenpai={t.get('tenpai')} waits={t.get('waits')} "
          f"有役荣和={t.get('has_yaku_ron')} 无役听牌={t.get('noyaku_ron')}")
    if s.get("claim"):
        print("    claim =", s["claim"])


def main() -> int:
    db = DB(DB_PATH)
    db.init_schema()
    db.close()

    r = api_cli.handle({"op": "start", "seat": 0, "dealer": 0}, DB_PATH)
    show("start", r)
    if not r["ok"]:
        return 1

    # 庄家摸牌 → 打一张 → 让下一家摸 ……
    for i in range(60):
        a = api_cli.handle({"op": "advance", "seat": 0}, DB_PATH)
        if not a["ok"]:
            print("advance 失败:", a["error"])
            return 1
        if a.get("result"):
            print(">>> 结局:", json.dumps(a["result"], ensure_ascii=False)[:300])
            break
        s = a["state"]
        acts = [x["action"] for x in s.get("legal", [])]
        if s["phase"] == "claim":
            print("  (鸣牌窗口) claim =", s.get("claim"))
            p = api_cli.handle({"op": "act", "seat": 0, "action": "pass"}, DB_PATH)
            show(f"#{i} pass", p)
            continue
        if "discard" not in acts:
            print("  轮到别人，跳过")
            continue
        hand = s["hand"]
        drawn = s.get("drawn") if len(hand) == 14 else None
        tile = hand[-1] if hand else None
        p = api_cli.handle({"op": "act", "seat": 0, "action": "discard", "tile": tile}, DB_PATH)
        show(f"#{i} 我打 {tile}", p)
        if p.get("result"):
            print("  >>> 结局:", json.dumps(p["result"], ensure_ascii=False)[:400])
            break

    # 纯判定接口
    t = api_cli.handle({"op": "tenpai", "seat": 0, "hand": "123m456m789m23p55s"}, DB_PATH)
    print("tenpai 判定:", {k: (t.get("tenpai") or {}).get(k)
                       for k in ("tenpai", "waits", "has_yaku_ron", "noyaku_ron")})
    j = api_cli.handle({"op": "judge", "seat": 0, "hand": "123m456m789m23p55s",
                        "tile": "4p", "tsumo": False}, DB_PATH)
    print("judge 判定:", (j.get("judge") or {}).get("yaku"), (j.get("judge") or {}).get("han"),
          "番", (j.get("judge") or {}).get("fu"), "符", (j.get("judge") or {}).get("pays", {}).get("total"))
    fn = api_cli.handle({"op": "furiten", "seat": 0, "hand": "123m456m789m23p55s",
                         "discards": ["4p"]}, DB_PATH)
    print("furiten 判定:", fn.get("furiten"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
