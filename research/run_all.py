"""Run every registered strategy over every symbol, write var/research/<name>_<symbol>.json and a markdown summary.
Usage: python -m research.run_all [--only orb,gap_fade] [--symbols SPX500_USD,NAS100_USD] [--workers 4]"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from .data import SYMBOLS, load_symbol
from .engine import PASS_BAR, evaluate
from .strategies import REGISTRY

OUT = Path(__file__).resolve().parents[1] / "var" / "research"
_DAYS: dict[str, list] = {}


def _days(symbol: str):
    if symbol not in _DAYS:
        _DAYS[symbol] = load_symbol(symbol)
    return _DAYS[symbol]


def one(job: tuple[str, str]) -> dict:
    name, symbol = job
    fn, grid, _ = REGISTRY[name]
    t0 = time.perf_counter()
    res = evaluate(name, symbol, fn, grid, _days(symbol))
    res["seconds"] = round(time.perf_counter() - t0, 1)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}_{symbol}.json").write_text(json.dumps(res, indent=1, default=str))
    return res


def summary_table(results: list[dict]) -> str:
    lines = ["| strategy | symbol | best params | trades | PF | PF@2x cost | win | avg bps | Sharpe | maxDD | folds+ | stable | verdict |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(results, key=lambda r: (-r["passed"], -r["best"]["pf"] if r["best"]["pf"] != float("inf") else 0)):
        b = r["best"]
        verdict = "PASS" if r["passed"] else "fail"
        lines.append(f"| {r['name']} | {r['symbol'].split('_')[0]} | {json.dumps(b['params'])} | {b['trades']} | {b['pf']} | {r['pf_at_2x_cost']} | "
                     f"{b['win_rate']:.0%} | {b['avg_bps']} | {b['sharpe']} | {b['max_dd_pct']}% | {b['folds_pos']}/5 | {r['stable_frac']:.0%} | {verdict} |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--symbols", default=",".join(SYMBOLS))
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    names = [n for n in a.only.split(",") if n] or list(REGISTRY)
    jobs = [(n, s) for n in names for s in a.symbols.split(",")]
    with ProcessPoolExecutor(a.workers) as ex:
        results = list(ex.map(one, jobs))
    md = ["# Intraday research results", "", f"Pass bar (set before running): PF ≥ {PASS_BAR['pf']} after {1.0} bp/side costs, "
          f"≥ {PASS_BAR['min_trades']} trades, all {PASS_BAR['folds']} chronological folds positive, ≥ {PASS_BAR['stable_frac']:.0%} of the "
          f"parameter grid with PF ≥ {PASS_BAR['stable_pf']}.", "", summary_table(results)]
    (OUT / "SUMMARY.md").write_text("\n".join(md))
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
