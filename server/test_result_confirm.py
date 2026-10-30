# -*- coding: utf-8 -*-
"""结算确认屏障：四家都确认才允许 op_next。"""
from __future__ import annotations
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")
import api_cli
import test_game as tg

PASS=FAIL=0

def check(name, got, want=True):
    global PASS,FAIL
    if got==want:
        PASS+=1; print("[OK]",name)
    else:
        FAIL+=1; print("[FAIL]",name,"got",got,"want",want)

def main():
    db=tg.fresh_db("result_confirm")
    # start a game using normal helper, then finish round
    r=api_cli.op_start(db,{"seat":0})
    rid=int(r["round_id"])
    db.finish_round(rid,"ryuukyoku")
    # Fake all four live leases; current pid is alive.
    with db.tx():
        for s in range(4):
            db.conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
                            (api_cli.LEASE_KEY%s, f"9999999999:{os.getpid()}"))
    for s in range(3):
        out=api_cli.op_result_confirm(db,{"seat":s})
        check(f"{s} 号确认后还没齐",out["result_confirm"]["ready"],False)
        nxt=api_cli.op_next(db,{"seat":s})
        check("next 被屏障挡住",nxt.get("waiting_confirm"),True)
    out=api_cli.op_result_confirm(db,{"seat":3})
    check("四家齐",out["result_confirm"]["ready"],True)
    check("确认列表",out["result_confirm"]["confirmed"],[0,1,2,3])
    nxt=api_cli.op_next(db,{"seat":3})
    check("放行下一局",not bool(nxt.get("waiting_confirm",False)),True)
    check("round_id 更新",int(nxt.get("round_id",rid))!=rid,True)
    db.close()
    print("通过",PASS,"失败",FAIL)
    return 0 if FAIL==0 else 1

if __name__=='__main__': raise SystemExit(main())
