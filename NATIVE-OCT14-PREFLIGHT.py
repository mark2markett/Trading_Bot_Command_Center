"""Read-only gate for the combined context/atomic-paper repair."""
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

SOURCE = json.loads(Path(__file__).with_name('OCT14-NATIVE-SOURCE.json').read_text())
TARGETS = tuple(SOURCE['stages']['installed'])
BOTS = {'sip_orb', 'gap_go', 'gap_go_spread', 'nr7', 'spy_mr'}


def check_git(root):
    result = subprocess.run(['git', 'diff', '--cached', '--name-only', '-z', '--'], cwd=root, capture_output=True)
    if result.returncode or result.stdout:
        raise ValueError('Git index is not clean or cannot be inspected; preserve staged changes.')
    result = subprocess.run(['git', 'status', '--porcelain', '-z', '--untracked-files=all', '--ignored=matching', '--', *TARGETS],
                            cwd=root, capture_output=True)
    if result.returncode or result.stdout:
        raise ValueError('A repair target has local changes or cannot be inspected; preserve it.')
    return {'ok': True, 'git': 'ready'}


def daily_queue(root, orders, connection, now):
    """Preserve one normal daily-paper BUY; never settle/cancel it for maintenance."""
    if not orders:
        return None, []
    error = 'Unresolved orders remain; only a matching idle SPY daily-paper BUY MOC can be preserved.'
    if len(orders) != 1 or any(name.startswith('bots/spy_mr_bot/') for name in TARGETS):
        raise ValueError(error)
    order = orders[0]
    if (order.get('bot_id'), order.get('side'), order.get('type'), order.get('status'), order.get('symbol')) != (
            'spy_mr', 'BUY', 'MOC', 'sent', 'SPY'):
        raise ValueError(error)
    if type(order.get('qty')) is not int or order['qty'] <= 0 or not re.fullmatch(r'paper-\d+', str(order.get('broker_order_id', ''))):
        raise ValueError(error)
    price = order.get('ref_price')
    if type(price) not in (int, float) or not math.isfinite(price) or price <= 0:
        raise ValueError('Pending reference price is missing or invalid.')
    at = datetime.fromisoformat(order['at'])
    if at.tzinfo is None:
        raise ValueError(error)
    at = at.astimezone(ZoneInfo('America/New_York'))
    age = now.date() - at.date()
    if at.weekday() >= 5 or (at.hour, at.minute) != (15, 50) or age not in (timedelta(0), timedelta(days=1)):
        raise ValueError('Daily pending order is outside its normal maintenance interval.')
    if (age == timedelta(0) and now.hour * 60 + now.minute < 975) or (age == timedelta(days=1) and now.hour * 60 + now.minute >= 560):
        raise ValueError('Daily pending order must finish its normal reconciliation first.')
    if connection.execute('SELECT 1 FROM fills WHERE order_id=? LIMIT 1', (order['id'],)).fetchone():
        raise ValueError('Pending daily order already has recorded fills; reconcile the mismatch first.')
    folder = root / 'bots/spy_mr_bot'
    paths = [folder / 'state_paper.json', folder / 'paper_ledger.json']
    if any(not path.is_file() or path.is_symlink() for path in paths):
        raise ValueError('Daily paper queue files are missing or not regular files.')
    raw = [path.read_bytes() for path in paths]
    state, paper = [json.loads(value) for value in raw]
    if not isinstance(state, dict) or not isinstance(paper, dict):
        raise ValueError('Daily paper queue files have an invalid structure.')
    cash = paper.get('cash')
    if type(cash) not in (int, float) or not math.isfinite(cash) or cash < 0:
        raise ValueError('Daily paper cash is missing or invalid; no maintenance exception applies.')
    date = at.date().isoformat()
    pending = state.get('pending')
    if (state.get('in_position') is not False or state.get('qty') != 0 or state.get('stop_order_id') is not None or
            state.get('last_decide') != date or not isinstance(pending, dict) or
            any(pending.get(key) != value for key, value in {
                'side': 'BUY', 'qty': order['qty'], 'date': date,
                'reason': 'rsi2_entry', 'order_id': order['broker_order_id']}.items())):
        raise ValueError('Daily state does not match the queued order; no maintenance exception applies.')
    positions, stops, queue, fills = [paper.get(key) for key in ('positions', 'stops', 'pending', 'fills')]
    if (not isinstance(positions, dict) or any(qty != 0 for qty in positions.values()) or stops != {} or
            not isinstance(queue, list) or len(queue) != 1 or not isinstance(queue[0], dict) or
            not isinstance(fills, list) or any(not isinstance(fill, dict) or fill.get('id') == order['broker_order_id'] for fill in fills)):
        raise ValueError('Daily paper ledger is not flat with one unfilled queue entry.')
    queued = queue[0]
    if any(queued.get(key) != value for key, value in {
            'id': order['broker_order_id'], 'kind': 'BUY_MOC', 'symbol': 'SPY', 'qty': order['qty']}.items()):
        raise ValueError('Daily paper broker queue does not match the order.')
    queued_at = datetime.fromisoformat(queued['queued'])
    if queued_at.tzinfo is None or abs((queued_at - at).total_seconds()) > 5:
        raise ValueError('Daily queue time does not match the submitted order.')
    identity = {'id': order['id'], 'symbol': 'SPY', 'qty': order['qty'], 'session_date': date}
    return identity, [hashlib.sha256(value).hexdigest() for value in raw]


def check(root, now=None):
    root = Path(root).resolve()
    now = (now or datetime.now(ZoneInfo('America/New_York'))).astimezone(ZoneInfo('America/New_York'))
    mod = now.hour * 60 + now.minute
    if 560 <= mod < 975:
        raise ValueError('Install after 16:15 ET or before 09:20 ET; no bot commands will be stopped.')
    hashes = {name: hashlib.sha256((root / name).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
              if (root / name).is_file() else None for name in TARGETS}
    stage = next((name for name, expected in SOURCE['stages'].items() if hashes == expected), None)
    if stage is None:
        raise ValueError('Unexpected repair source; preserve local files and collect a review.')
    database = Path(os.environ.get('CC_VAR', root / 'var')).resolve() / 'cc.db'
    if not database.is_file():
        raise ValueError('Trading ledger is missing; refusing to create one.')
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=5) as connection:
        bots = dict(connection.execute('SELECT id,mode FROM bots'))
        if set(bots) != BOTS or any(mode != 'paper' for mode in bots.values()):
            raise ValueError('Expected exactly the five registered paper bots.')
        if connection.execute('SELECT 1 FROM positions WHERE qty != 0 LIMIT 1').fetchone():
            raise ValueError('Open positions remain; finish normal exit handling first.')
        connection.row_factory = sqlite3.Row
        orders = [dict(row) for row in connection.execute(
            "SELECT * FROM orders WHERE status IN ('sent','submitted','pending','open','partially_filled') ORDER BY rowid")]
        preserved, files = daily_queue(root, orders, connection, now)
    fingerprint = hashlib.sha256(json.dumps({'orders': orders, 'daily_files': files}, sort_keys=True).encode()).hexdigest()
    return {'ok': True, 'source': stage, 'at_et': now.isoformat(),
            'preserved_daily_order': preserved, 'runtime_fingerprint': fingerprint}


if __name__ == '__main__':
    try:
        print(json.dumps(check_git(sys.argv[1]) if '--git-only' in sys.argv[2:] else check(sys.argv[1])))
    except (OSError, ValueError, sqlite3.Error) as error:
        print(json.dumps({'ok': False, 'error': str(error)}))
        raise SystemExit(1)
