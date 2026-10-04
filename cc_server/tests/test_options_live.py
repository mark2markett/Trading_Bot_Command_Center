"""M7.4: the bot summary carries the live Greeks a spread bot wrote to kv, matched by exact prefix."""
import json

from cc_sdk.ledger import Ledger
from cc_server import db


def test_kv_prefix_is_exact_not_like(tmp_path):
    L = Ledger(tmp_path / "cc.db")
    rec = {"underlying": "SPY", "delta_shares": 380.0, "theta_usd_day": -12.5, "dte": 2}
    for key, val in (("optlive:gap_go_spread:SPY", rec), ("optlive:gapXgo_spread:QQQ", {"underlying": "QQQ"}),
                     ("spread:gap_go_spread:SPY", {"other": 1})):
        L.x("INSERT INTO kv(key,value_json,updated_at) VALUES(?,?,?)", (key, json.dumps(val), "t"))
    assert db.kv_prefix(L, "optlive:gap_go_spread:") == [rec]       # `_` is literal: gapXgo does not match
    assert db.kv_prefix(L, "optlive:nobody:") == []
