from __future__ import annotations

import argparse,os
import uvicorn


def main():
    parser=argparse.ArgumentParser(description="Local Mission Control preview")
    parser.add_argument("--username",required=True)
    parser.add_argument("--password",required=True)
    parser.add_argument("--port",type=int,default=8765)
    args=parser.parse_args()
    os.environ["MISSION_CONTROL_USERNAME"]=args.username
    os.environ["MISSION_CONTROL_PASSWORD"]=args.password
    os.environ.setdefault("MISSION_CONTROL_DATABASE",".ambassador/mission_control.db")
    uvicorn.run("mission_control.app:app",host="127.0.0.1",port=args.port,log_level="warning")


if __name__=="__main__": main()
