"""Initialize the user-approved shared paper account once; never reset P&L on rerun."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cc_sdk"))
from cc_sdk.ledger import Ledger
from cc_sdk.paper_account import configure, snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capital", type=float, required=True)
    args = parser.parse_args()
    ledger = Ledger()
    try:
        configure(ledger, args.capital)
        print(json.dumps(snapshot(ledger)))
    finally:
        ledger.conn.close()


if __name__ == "__main__":
    main()
