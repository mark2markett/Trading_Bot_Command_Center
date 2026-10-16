"""Read-only SPY simulator/CC reconciliation proposal. No providers, orders or corrections.

Run after daily bot commands finish: python scripts/audit_spy_paper.py [--repo path]
Output is private financial evidence; store locally or in the private review bundle.
"""
import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def audit(repo: Path) -> dict:
    paths = [repo / 'bots/spy_mr_bot' / name for name in ('state_paper.json', 'paper_ledger.json')]
    payloads = [path.read_bytes() for path in paths]
    state, broker = [json.loads(payload) for payload in payloads]
    with sqlite3.connect((repo / 'var/cc.db').resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN')
        position = db.execute("SELECT qty,avg_price,stop_price FROM positions WHERE bot_id='spy_mr' AND symbol='SPY'").fetchone()
        fills = [dict(row) for row in db.execute("SELECT f.qty,f.price,f.commission,o.broker_order_id FROM fills f LEFT JOIN orders o ON o.id=f.order_id WHERE f.bot_id='spy_mr'")]
    if any(path.read_bytes() != payload for path, payload in zip(paths, payloads, strict=True)):
        raise ValueError('SNAPSHOT_CHANGED_RECOLLECT_WHEN_IDLE')
    qty = state.get('qty', 0) if state.get('in_position') else 0
    issues, discrepancies, missing = [], [], []
    if qty != broker.get('positions', {}).get('SPY', 0) or qty != (position['qty'] if position else 0):
        issues.append('QUANTITY_MISMATCH')
    basis = qty * (float(state.get('entry_price') or 0) - float(position['avg_price'] or 0)) if qty and position else None
    if basis is not None and abs(basis) > 1e-8:
        issues.append('ENTRY_BASIS_MISMATCH')
    for event in broker.get('fills', []):
        if 'commission' not in event:
            missing.append(event.get('id'))
        matches = [row for row in fills if row['broker_order_id'] == event.get('order_id', event.get('id'))]
        if len(matches) != 1:
            discrepancies.append({'event_id': event.get('id'), 'reason': 'MISSING_OR_AMBIGUOUS_CC_FILL'})
            continue
        row = matches[0]
        price_difference = (float(event['fill']) - row['price']) * event['qty']
        fee_difference = float(event['commission']) - (row['commission'] or 0) if 'commission' in event else None
        if abs(price_difference) > 1e-8 or fee_difference is None or abs(fee_difference) > 1e-8 or row['qty'] != event['qty']:
            discrepancies.append({'event_id': event.get('id'), 'price_difference_dollars': price_difference,
                                  'commission_difference': fee_difference, 'qty_matches': row['qty'] == event['qty']})
    stop = broker.get('stops', {}).get('SPY')
    if qty and (not stop or stop.get('qty') != qty or stop.get('id', state.get('stop_order_id')) != state.get('stop_order_id')):
        issues.append('PROTECTIVE_STOP_IDENTITY_REVIEW')
    if qty and position and (not stop or position['stop_price'] != stop.get('stop')):
        issues.append('CC_STOP_DISPLAY_MISMATCH')
    if discrepancies:
        issues.append('FILL_COST_RECONCILIATION_REQUIRED')
    if missing:
        issues.append('HISTORICAL_COST_EVIDENCE_MISSING')
    return {'at': datetime.now(timezone.utc).isoformat(), 'status': 'REVIEW_REQUIRED' if issues else 'CONSISTENT_OBSERVATION',
            'issues': issues, 'basis_difference_dollars': basis, 'fill_discrepancies': discrepancies,
            'missing_cost_event_ids': missing, 'simulator_stop': {key: stop.get(key) for key in ('id', 'qty', 'stop')} if stop else None,
            'input_sha256': [hashlib.sha256(payload).hexdigest() for payload in payloads], 'automatic_corrections': 0,
            'next_action': 'Retain original records; obtain actual event/cost evidence and review additive corrections. Do not restore an old database.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        result = audit(args.repo)
        print(json.dumps(result, indent=2, allow_nan=False))
        raise SystemExit(0 if result['status'] == 'CONSISTENT_OBSERVATION' else 2)
    except (OSError, ValueError, KeyError, sqlite3.Error) as error:
        print(json.dumps({'status': 'EVIDENCE_UNAVAILABLE', 'error': type(error).__name__, 'automatic_corrections': 0}))
        raise SystemExit(2) from None
