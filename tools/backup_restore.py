"""Verified MongoDB backup, retention, preview and guarded restore."""
import argparse, hashlib, json, tempfile, zipfile
from datetime import datetime, timezone
from pathlib import Path
from bson import json_util
from pymongo import MongoClient
from app_core.audit import record_audit_event
from app_core.config import get_config

def digest(data): return hashlib.sha256(data).hexdigest()
def client_db():
    c=get_config(); client=MongoClient(c.mongodb_uri, serverSelectionTimeoutMS=c.service_timeout_ms)
    client.admin.command("ping"); return client, client[c.mongodb_database]

def create_backup(label="manual", keep=10):
    cfg=get_config(); root=cfg.data_dir/"backups"; root.mkdir(parents=True, exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target=root/f"eyres_backup_{stamp}_{label}.zip"
    client, db=client_db()
    try:
        manifest={"format":1,"created_utc":datetime.now(timezone.utc).isoformat(),
                  "database":cfg.mongodb_database,"collections":{},"files":{}}
        with tempfile.TemporaryDirectory() as folder:
            stage=Path(folder)
            for name in sorted(db.list_collection_names()):
                payload="\n".join(json_util.dumps(x) for x in db[name].find({}))
                if payload: payload+="\n"
                data=payload.encode(); filename=f"collections/{name}.jsonl"
                manifest["collections"][name]=db[name].count_documents({})
                manifest["files"][filename]=digest(data)
                path=stage/filename; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
            (stage/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
            with zipfile.ZipFile(target,"w",zipfile.ZIP_DEFLATED) as archive:
                for path in stage.rglob("*"):
                    if path.is_file(): archive.write(path,path.relative_to(stage))
    finally: client.close()
    backups=sorted(root.glob("eyres_backup_*.zip"),key=lambda p:p.stat().st_mtime,reverse=True)
    for old in backups[max(1,keep):]: old.unlink()
    record_audit_event("backup_created",details={"file":target.name,"collections":len(manifest["collections"])})
    return target

def inspect_backup(path):
    path=Path(path)
    with zipfile.ZipFile(path) as archive:
        manifest=json.loads(archive.read("manifest.json"))
        for name, expected in manifest["files"].items():
            if digest(archive.read(name)) != expected: raise ValueError(f"Checksum failed: {name}")
    return manifest

def restore(path, apply=False, confirmation=""):
    manifest=inspect_backup(path)
    if not apply: return {"mode":"preview",**manifest}
    if confirmation != "RESTORE EYRES DATABASE": raise ValueError("Exact restore confirmation is required")
    safety=create_backup("pre_restore",keep=10)
    client, db=client_db()
    try:
        with zipfile.ZipFile(path) as archive:
            for name in manifest["collections"]:
                rows=[json_util.loads(x) for x in archive.read(f"collections/{name}.jsonl").decode().splitlines() if x]
                db[name].delete_many({})
                if rows: db[name].insert_many(rows,ordered=True)
    finally: client.close()
    record_audit_event("database_restored",details={"backup":Path(path).name,"safety_backup":safety.name})
    return {"mode":"applied","safety_backup":str(safety),**manifest}

def main():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest="command",required=True)
    b=sub.add_parser("backup"); b.add_argument("--keep",type=int,default=10)
    v=sub.add_parser("verify"); v.add_argument("backup")
    r=sub.add_parser("restore"); r.add_argument("backup"); r.add_argument("--apply",action="store_true"); r.add_argument("--confirm",default="")
    a=p.parse_args()
    if a.command=="backup": print(create_backup(keep=a.keep))
    elif a.command=="verify": print(json.dumps(inspect_backup(a.backup),indent=2))
    else: print(json.dumps(restore(a.backup,a.apply,a.confirm),indent=2))
if __name__=="__main__": main()
