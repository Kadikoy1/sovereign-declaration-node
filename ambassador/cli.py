from __future__ import annotations

import argparse
from pathlib import Path

from .ledger import OutreachLedger


def main() -> None:
    parser=argparse.ArgumentParser(description="Sovereign Ambassador v0.1")
    parser.add_argument("command",choices=("discover","cohort"))
    parser.add_argument("--ledger",default=".ambassador/outreach.db")
    parser.add_argument("--dry-run",action="store_true")
    args=parser.parse_args()
    OutreachLedger(Path(args.ledger))
    if args.command == "cohort" and not args.dry_run:
        raise SystemExit("Live cohort requires a separately configured authenticated runner; no transmission occurred")
    print("Ambassador initialized in dry-run mode; no transmission occurred")


if __name__ == "__main__": main()
