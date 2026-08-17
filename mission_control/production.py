from __future__ import annotations

import base64
import gzip
import hashlib
import os
from pathlib import Path

import uvicorn


def _seed_database(path: Path, value_name: str, digest_name: str) -> None:
    if path.exists():
        return
    encoded=os.getenv(value_name)
    expected=os.getenv(digest_name)
    if not encoded or not expected:
        raise RuntimeError(f"Missing initial persistent state: {value_name} and {digest_name}")
    payload=gzip.decompress(base64.b64decode(encoded,validate=True))
    actual=hashlib.sha256(payload).hexdigest()
    if actual != expected.lower():
        raise RuntimeError(f"Initial persistent state digest mismatch for {path.name}")
    temporary=path.with_suffix(path.suffix+".initializing")
    temporary.write_bytes(payload)
    os.chmod(temporary,0o600)
    temporary.replace(path)


def main() -> None:
    required=("MISSION_CONTROL_USERNAME","MISSION_CONTROL_PASSWORD","MISSION_CONTROL_DATABASE")
    missing=[name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError("Missing Mission Control production configuration: "+", ".join(missing))
    database=Path(os.environ["MISSION_CONTROL_DATABASE"])
    outreach=Path(os.getenv("MISSION_CONTROL_OUTREACH_DATABASE",str(database.with_name("outreach.db"))))
    database.parent.mkdir(parents=True,exist_ok=True)
    _seed_database(database,"MISSION_CONTROL_SEED_DATABASE_GZIP_B64","MISSION_CONTROL_SEED_DATABASE_SHA256")
    _seed_database(outreach,"MISSION_CONTROL_SEED_OUTREACH_GZIP_B64","MISSION_CONTROL_SEED_OUTREACH_SHA256")
    uvicorn.run("mission_control.app:create_app",factory=True,host="0.0.0.0",
                port=int(os.getenv("PORT","8080")),proxy_headers=True,forwarded_allow_ips="*")


if __name__=="__main__": main()
