#!/usr/bin/env python3
"""Full-audit and losslessly migrate a stopped/paused Living Kanto save."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from living_kanto.store.run_store import RunStore


def prefix_digest(db, run_id):
    digest=hashlib.sha256()
    for row in db.execute('SELECT event_index,event_hash FROM events WHERE run_id=? ORDER BY event_index',(run_id,)):
        digest.update(f'{row[0]}:{row[1]}\n'.encode())
    return digest.hexdigest()


def migrate(path, run_id, allow_running_snapshot=False):
    start=time.monotonic();store=RunStore(path)
    try:
        if not allow_running_snapshot and store.get_status(run_id)!='paused':
            raise ValueError('Pause/stop simulation before migration; use --snapshot only for isolated copies')
        row=store._get_run_row(run_id)
        before={k:row[k] for k in ['state_version','state_hash','head_hash','status']}
        before['history_digest']=prefix_digest(store._db,run_id)
        before['file_bytes']=path.stat().st_size
        report=store.optimize_storage(run_id)
        migration_seconds=time.monotonic()-start
        store._conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        store._conn.execute('VACUUM')
        if store._conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise RuntimeError('SQLite integrity check failed')
        store._conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        store.close();store=RunStore(path)
        cold=time.monotonic();_,state,head=store.load_run(run_id);cold_seconds=time.monotonic()-cold
        after={k:store._get_run_row(run_id)[k] for k in ['state_version','state_hash','head_hash','status']}
        after['history_digest']=prefix_digest(store._db,run_id)
        if any(before[k]!=after[k] for k in after):
            raise RuntimeError('Migration changed canonical save bindings')
        return {'before':before,'after':{**after,'file_bytes':path.stat().st_size},
                'population':len(state.humans),'pokemon':len(state.pokemon),'memories':sum(len(h.get('memories',{})) for h in state.humans.values()),
                'migration_seconds':migration_seconds,'cold_load_seconds':cold_seconds,'storage':store.storage_status(run_id),
                'state_hash_verified':state.compute_state_hash()==state.state_hash}
    finally:
        store.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database',required=True,type=Path)
    p.add_argument('--run-id',required=True)
    p.add_argument('--snapshot',action='store_true',help='Allow running status only on an isolated snapshot copy, never a live service database')
    p.add_argument('--report',required=True,type=Path)
    args=p.parse_args();result=migrate(args.database,args.run_id,args.snapshot)
    args.report.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2),flush=True)
