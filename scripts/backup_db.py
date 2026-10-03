"""Nightly copy of var/cc.db to var/backups/, keeping the last 7. Uses sqlite's online backup API (safe with WAL)."""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cc_sdk"))
from cc_sdk.ledger import db_path  # noqa: E402

src = db_path()
dst_dir = src.parent / "backups"
dst_dir.mkdir(exist_ok=True)
dst = dst_dir / f"cc-{datetime.now():%Y%m%d}.db"
with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
    s.backup(d)
for old in sorted(dst_dir.glob("cc-*.db"))[:-7]:
    old.unlink()
print(dst)
