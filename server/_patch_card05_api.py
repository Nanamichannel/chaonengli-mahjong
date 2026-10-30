# -*- coding: utf-8 -*-
import io

P = "api_cli.py"
t = io.open(P, encoding="utf-8").read()


def sub(old, new):
    global t
    assert old in t, "NOT FOUND: " + old[:100]
    t = t.replace(old, new, 1)


sub('''def op_wind_swap(db: DB, req: dict) -> dict:
''',
    '''def op_card05_extra(db: DB, req: dict) -> dict:
    """Card05 Skill1「策略」：花 1 点计数，换一次额外的摸切。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.card05_extra_activate(seat)
    return {"ok": True, "card05": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_card05_swap(db: DB, req: dict) -> dict:
    """Card05 Skill1：王牌 / 弃牌 一张 ↔ 自己一张手牌。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.card05_swap(seat, str(req.get("hand", "")), str(req.get("kind", "")),
                      int(req.get("stack", 0) or 0), str(req.get("half", "top")),
                      int(req.get("river", -1) or -1))
    return {"ok": True, "card05_swap": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_card05_cancel(db: DB, req: dict) -> dict:
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.card05_cancel(seat)
    return {"ok": True, "card05_cancel": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_card05_hide(db: DB, req: dict) -> dict:
    """Card05 Skill1：被看手牌时盖住最多三张。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.card05_hide(seat, [str(x) for x in (req.get("tiles") or [])])
    return {"ok": True, "card05_hide": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_view_hand(db: DB, req: dict) -> dict:
    """看某个座位的手牌（策略：盖住的三张看不到；第一次看会先让对方选盖哪三张）。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    target = int(req.get("target", -1))
    r = g.card05_view_hand(seat, target)
    return {"ok": True, "view": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_wind_swap(db: DB, req: dict) -> dict:
''')

sub('''    "wind_swap": op_wind_swap,
''',
    '''    "wind_swap": op_wind_swap,
    "card05_extra": op_card05_extra,
    "card05_swap": op_card05_swap,
    "card05_cancel": op_card05_cancel,
    "card05_hide": op_card05_hide,
    "view_hand": op_view_hand,
''')
io.open(P, "w", encoding="utf-8", newline="").write(t)
print("api_cli.py ok")
