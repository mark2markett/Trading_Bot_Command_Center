"""Read-only gate for the combined context/atomic-paper repair."""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime
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
        if connection.execute("SELECT 1 FROM orders WHERE status IN ('sent','submitted','pending','open','partially_filled') LIMIT 1").fetchone():
            raise ValueError('Unresolved orders remain; reconcile first.')
    return {'ok': True, 'source': stage, 'at_et': now.isoformat()}


if __name__ == '__main__':
    try:
        print(json.dumps(check_git(sys.argv[1]) if '--git-only' in sys.argv[2:] else check(sys.argv[1])))
    except (OSError, ValueError, sqlite3.Error) as error:
        print(json.dumps({'ok': False, 'error': str(error)}))
        raise SystemExit(1)
