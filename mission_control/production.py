from __future__ import annotations

import os
from pathlib import Path

import uvicorn


def main() -> None:
    required=("MISSION_CONTROL_USERNAME","MISSION_CONTROL_PASSWORD","MISSION_CONTROL_DATABASE")
    missing=[name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError("Missing Mission Control production configuration: "+", ".join(missing))
    Path(os.environ["MISSION_CONTROL_DATABASE"]).parent.mkdir(parents=True,exist_ok=True)
    uvicorn.run("mission_control.app:create_app",factory=True,host="0.0.0.0",
                port=int(os.getenv("PORT","8080")),proxy_headers=True,forwarded_allow_ips="*")


if __name__=="__main__": main()
