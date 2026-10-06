#!/usr/bin/env python3
"""Catch up a fully audited v2 snapshot to a paused v1 save, without changing either."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from living_kanto.contracts import WorldState
from living_kanto.contracts.base import canonical_json
from living_kanto.store.run_store import RunStore
from living_kanto.store.storage_layout import unpack


def finish(snapshot, live, output, run_id):
    if output.exists() or output.resolve() in {live.resolve(),snapshot.resolve()}:
        raise ValueError('Output must be a new isolated database')
    source=sqlite3.connect('file:'+str(live)+'?mode=ro',uri=True)
    source.row_factory=sqlite3.Row;source.execute('BEGIN')
    row=source.execute('SELECT * FROM runs WHERE run_id=?',(run_id,)).fetchone()
    if row is None or row['status']!='paused' or ('storage_version' in row.keys() and row['storage_version']!=1):
        raise ValueError('Source must be the paused, stopped legacy save')
    snap=sqlite3.connect('file:'+str(snapshot)+'?mode=ro',uri=True);dst=sqlite3.connect(output)
    snap.backup(dst);snap.close();dst.close()
    target=RunStore(output);start=time.monotonic()
    try:
        _,initial,_=target.load_run(run_id)
        if initial.state_version>row['state_version']:
            raise ValueError('Snapshot is newer than paused source')
        target_row=target._get_run_row(run_id)
        for key in ['genesis_json','genesis_hash','metadata_json']:
            if row[key]!=target_row[key]:raise ValueError('Source identity/genesis changed')
        prefix=hashlib.sha256();tail=[];count=0
        for r in source.execute('SELECT * FROM events WHERE run_id=? ORDER BY event_index',(run_id,)):
            if r['event_index']!=count:
                raise ValueError('Original event prefix is not contiguous')
            count+=1
            if r['event_index']<initial.state_version:
                t=target._db.execute('SELECT * FROM events WHERE run_id=? AND event_index=?',(run_id,r['event_index'])).fetchone()
                if t is None or any(r[k]!=t[k] for k in ['event_index','event_id','event_hash','previous_head','state_after_hash']):
                    raise ValueError('Original event prefix changed')
                if canonical_json(unpack(r['event_json']))!=canonical_json(unpack(t['event_json'])):
                    raise ValueError('Original event content changed')
            else:
                event=target._decode_event(r['event_json'])
                if (event.run_id!=run_id or event.event_index!=r['event_index']
                    or event.event_id!=r['event_id'] or event.previous_head!=r['previous_head']
                    or event.event_hash!=r['event_hash']
                    or event.transaction['state_hash']!=r['state_after_hash']):
                    raise ValueError('Tail event columns differ from canonical payload')
                tail.append(event)
            prefix.update(f"{r['event_index']}:{r['event_hash']}\n".encode())
        if count!=row['state_version'] or count<initial.state_version:
            raise ValueError('Original event prefix count differs from committed version')
        target.set_status(run_id,'running')
        for n,event in enumerate(tail):
            target.append_event(event,event.transaction['state_hash'])
            if (n+1)%100==0:print(json.dumps({'tail_applied':n+1,'tail_events':len(tail)}),flush=True)
        target.set_status(run_id,'paused')
        _,state,head=target.load_run(run_id)
        source_state=WorldState.from_dict(json.loads(row['state_json'])).verify()
        if state.to_dict()!=source_state.to_dict() or head!=row['head_hash']:
            raise ValueError('Caught-up world differs from paused source')
        for key in ['state_version','state_hash','tick','simulated_time','head_hash']:
            if target._get_run_row(run_id)[key]!=row[key]:raise ValueError('Save binding changed: '+key)
        with target._db:
            target._write_checkpoint(state,head,target._get_run_row(run_id)['prefix_digest'])
        target.close();target=RunStore(output)
        cold=time.monotonic();_,verified,_=target.load_run(run_id);cold_seconds=time.monotonic()-cold
        if verified.to_dict()!=state.to_dict():raise ValueError('Cold verification changed world')
        target._db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        target._db.execute('VACUUM')
        if target._db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('SQLite integrity check failed')
        target._db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        return {'run_id':run_id,'from_version':initial.state_version,'state_version':state.state_version,
                'state_hash':state.state_hash,'head_hash':head,'history_digest':prefix.hexdigest(),
                'tail_events':len(tail),'population':len(state.humans),'pokemon':len(state.pokemon),
                'memories':sum(len(h.get('memories',{})) for h in state.humans.values()),
                'original_bytes':live.stat().st_size,'optimized_bytes':output.stat().st_size,
                'catchup_seconds':time.monotonic()-start,'cold_load_seconds':cold_seconds,
                'storage':target.storage_status(run_id),'world_contents_preserved':True}
    finally:
        target.close();source.rollback();source.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot',type=Path,required=True);p.add_argument('--live',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--run-id',required=True)
    p.add_argument('--report',type=Path,required=True);args=p.parse_args()
    result=finish(args.snapshot,args.live,args.output,args.run_id)
    args.report.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2),flush=True)
