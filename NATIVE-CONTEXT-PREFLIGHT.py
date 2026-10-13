"""Read-only installation gate; never changes the trading database or controls."""
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ORIGINAL = 'e9203ffb83543debc2ad5e3381845e7dd2875ac57457b49531dde3595dd6ed9d'
UPDATED = '934d6d1cb0004365b07e8992cd1155349a6bc3bbd7d0823d0f283816651ce56e'
BOTS = {'sip_orb', 'gap_go', 'gap_go_spread', 'nr7', 'spy_mr'}


def check(root, now=None):
    root = Path(root).resolve()
    now = (now or datetime.now(ZoneInfo('America/New_York'))).astimezone(ZoneInfo('America/New_York'))
    mod = now.hour * 60 + now.minute
    if now.weekday() < 5 and 560 <= mod < 975:
        raise ValueError('Install after 16:15 ET or before 09:20 ET; no sessions will be stopped.')
    source = root / 'cc_sdk/cc_sdk/intraday.py'
    digest = hashlib.sha256(source.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
    if digest not in {ORIGINAL, UPDATED}:
        raise ValueError('Unexpected intraday source; preserve local changes and collect a review.')
    var = Path(os.environ.get('CC_VAR', root / 'var')).resolve()
    database = var / 'cc.db'
    if not database.is_file():
        raise ValueError('Trading ledger is missing; refusing to create one.')
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=5) as connection:
        bots = dict(connection.execute('SELECT id,mode FROM bots'))
        if set(bots) != BOTS or any(mode != 'paper' for mode in bots.values()):
            raise ValueError('Expected exactly the five registered paper bots.')
        if connection.execute('SELECT 1 FROM positions WHERE qty != 0 LIMIT 1').fetchone():
            raise ValueError('Open positions remain; finish normal exit handling before installing.')
        if connection.execute("SELECT 1 FROM orders WHERE status IN ('sent','submitted','pending','open','partially_filled') LIMIT 1").fetchone():
            raise ValueError('Unresolved orders remain; reconcile before installing.')
    return {'ok': True, 'source': 'installed' if digest == UPDATED else 'ready', 'at_et': now.isoformat()}


if __name__ == '__main__':
    try:
        print(json.dumps(check(sys.argv[1])))
    except (OSError, ValueError, sqlite3.Error) as error:
        print(json.dumps({'ok': False, 'error': str(error)}))
        raise SystemExit(1)
