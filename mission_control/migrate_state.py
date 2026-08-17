from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

DATABASES=("outreach.db","mission_control.db")


def _backup(source: Path,destination: Path) -> None:
    with sqlite3.connect(source) as src,sqlite3.connect(destination) as dst:
        src.backup(dst)
        if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError(f"Integrity check failed for {destination.name}")


def _semantic_digest(path: Path) -> str:
    with sqlite3.connect(path) as db:
        tables=[x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        data={table:db.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall() for table in tables}
    return hashlib.sha256(json.dumps(data,sort_keys=True,default=str,separators=(",",":")).encode()).hexdigest()


def migrate(source_dir: Path,destination_dir: Path) -> dict:
    destination_dir.mkdir(parents=True,exist_ok=True)
    report={}
    for name in DATABASES:
        source=source_dir/name; destination=destination_dir/name
        if not source.is_file(): raise FileNotFoundError(source)
        if destination.exists(): raise FileExistsError(destination)
        before=_semantic_digest(source); _backup(source,destination); after=_semantic_digest(destination)
        if before != after: raise RuntimeError(f"Semantic migration mismatch for {name}")
        report[name]={"semantic_sha256":after,"integrity":"ok"}
    with sqlite3.connect(destination_dir/"outreach.db") as db:
        report["cohort_1_records"]=db.execute("SELECT count(*) FROM outreach").fetchone()[0]
    with sqlite3.connect(destination_dir/"mission_control.db") as db:
        report["mission_control_agents"]=db.execute("SELECT count(*) FROM agents").fetchone()[0]
        report["mission_control_candidates"]=db.execute("SELECT count(*) FROM network_candidates").fetchone()[0]
    if report["cohort_1_records"] != 5 or report["mission_control_agents"] != 5:
        raise RuntimeError("Commissioning state count mismatch")
    return report


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument("source",type=Path); parser.add_argument("destination",type=Path)
    args=parser.parse_args(); print(json.dumps(migrate(args.source,args.destination),indent=2))


if __name__=="__main__": main()
