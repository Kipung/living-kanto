#!/usr/bin/env python3
"""Guarded Spark operator: install a fully audited v2 snapshot plus verified tail."""
from pathlib import Path
import fcntl
import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request

ROOT=Path('/home/kip/living-kanto-deploy/living-kanto')
WORK=ROOT/'work/storage-v2';CANDIDATE=WORK/'candidate'
RUN='fast-ai-live-20261005-v2';PY='/home/kip/living-kanto-deploy/venv/bin/python'
FILES=['server/living_kanto/store/run_store.py','server/living_kanto/store/storage_layout.py',
       'server/living_kanto/contracts/state.py','server/living_kanto/api/app.py','server/living_kanto/api/world_api.py',
       'server/living_kanto/api/history_paging.py','client/unified/person.mjs','client/unified/history-pager.mjs']


def api(action,body=None,timeout=30):
    data=json.dumps(body or {}).encode() if action in {'pause','resume'} else None
    req=urllib.request.Request('http://127.0.0.1:8878/runs/'+RUN+'/'+action,data=data,
        headers={'Content-Type':'application/json'},method='POST' if data is not None else 'GET')
    with urllib.request.urlopen(req,timeout=timeout) as r:return json.load(r)


def source_manifest():
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (ROOT/'server/living_kanto').rglob('*')
            if p.is_file() and 'node_modules' not in p.parts and p.suffix in {'.py','.cjs'}}
    for relative in ['client/unified/person.mjs','client/unified/history-pager.mjs']:
        if (ROOT/relative).exists():hashes[relative]=hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()
    return hashes


def log(stage,**values):print(json.dumps({'stage':stage,**values}),flush=True)


def main():
    lock=(WORK/'deploy.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    report=json.loads((WORK/'snapshot-migration.json').read_text())
    if not report.get('state_hash_verified') or report['storage']['storage_version']!=2:
        raise ValueError('Verified snapshot report missing')
    expected=json.loads((CANDIDATE/'baseline-hashes.json').read_text())
    expected['server/living_kanto/contracts/state.py']='7ae83e09e1dc85f296d897e3bf6c1d17988bfbf782521bd058d5af77864c1840'
    for f,sha in expected.items():
        if hashlib.sha256((ROOT/f).read_bytes()).hexdigest()!=sha:
            raise ValueError('Live preimage changed, abort before pause: '+f)
    runtime=api('runtime')
    if runtime.get('failure') is not None or not runtime['running']:
        raise ValueError('Live world must be healthy and running before planned migration')
    before_sources=source_manifest()
    validation=json.loads((CANDIDATE/'validated-source.json').read_text())
    if not validation['passed']:raise ValueError('Candidate validation did not pass')
    for relative,sha in validation['hashes'].items():
        if hashlib.sha256((CANDIDATE/relative).read_bytes()).hexdigest()!=sha:
            raise ValueError('Validated candidate changed: '+relative)
    for relative,sha in before_sources.items():
        if relative not in FILES and validation['hashes'].get(relative)!=sha:
            raise ValueError('Unrelated live source changed; rebase and validate before pause: '+relative)
    stamp=time.strftime('%Y%m%d-%H%M%S',time.gmtime());backup=ROOT/'backups'/('storage-v2-'+stamp)
    backup.mkdir(parents=True,exist_ok=False)
    (backup/'runtime-before.json').write_text(json.dumps(runtime,indent=2))
    (backup/'source-hashes.json').write_text(json.dumps(before_sources,indent=2))
    for relative in before_sources:
        dest=backup/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/relative,dest)
    database=ROOT/'data'/f'{RUN}.db';original=backup/f'{RUN}.db'
    installed=False;stopped=False;resume_requested=False
    try:
        log('pausing',snapshot_version=report['after']['state_version'])
        api('pause',timeout=60)
        subprocess.run(['systemctl','--user','stop','living-kanto.service'],check=True);stopped=True
        if source_manifest()!=before_sources:raise ValueError('Live source changed before service stopped')
        # A stopped process can leave committed WAL pages behind. Fold those
        # into the main file before backup/catch-up, with no semantic change.
        checkpoint=sqlite3.connect(database,timeout=30)
        try:
            if checkpoint.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]!=0:
                raise ValueError('Original WAL is busy after service stop')
        finally:checkpoint.close()
        source=sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True)
        dst=sqlite3.connect(original);source.backup(dst);dst.close();source.close()
        settings=database.with_suffix('.runtime-settings.json')
        if settings.exists():shutil.copy2(settings,backup/settings.name)
        log('backup_ready',backup=str(backup),database_bytes=original.stat().st_size)
        final=WORK/'final-migrated.db'
        subprocess.run([PY,str(CANDIDATE/'tools/finish_run_storage_migration.py'),
            '--snapshot',str(WORK/'test-snapshot.db'),'--live',str(database),'--output',str(final),
            '--run-id',RUN,'--report',str(WORK/'live-migration.json')],check=True)
        if source_manifest()!=before_sources:raise ValueError('Live source changed during migration')
        for relative in FILES:
            target=ROOT/relative;target.parent.mkdir(parents=True,exist_ok=True)
            temporary=target.with_name('.'+target.name+'.storage-v2')
            shutil.copy2(CANDIDATE/relative,temporary);os.replace(temporary,target)
        # All SQLite connections are closed and the service is stopped. Final
        # candidate was checkpointed, compacted and integrity/cold-load checked.
        for suffix in ['-wal','-shm']:
            companion=Path(str(database)+suffix)
            if companion.exists():
                if suffix=='-wal' and companion.stat().st_size>0:
                    raise ValueError('Uncheckpointed original WAL; refuse replacement')
                companion.unlink()
        os.replace(final,database);installed=True
        fd=os.open(database.parent,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
        for relative in ['tools/optimize_run_storage.py','tools/finish_run_storage_migration.py','tools/manage_storage_backups.py']:
            shutil.copy2(CANDIDATE/relative,ROOT/relative)
        subprocess.run(['systemctl','--user','start','living-kanto.service'],check=True);stopped=False
        log('source_and_database_installed',backup=str(backup))
        deadline=time.monotonic()+180
        while True:
            try:
                if api('runtime',timeout=60).get('state_version') is not None:break
            except (OSError,TimeoutError):
                if time.monotonic()>deadline:raise
                time.sleep(2)
        # A request timeout can occur after the server starts committing. From
        # this boundary onwards rollback must NEVER replace fresh history.
        resume_requested=True
        api('resume',{'speed':runtime.get('speed','fastest')},timeout=60)
        acceptance={'backup':str(backup),'migration':json.loads((WORK/'live-migration.json').read_text()),
                    'runtime_after_resume':api('runtime'),'installed_hashes':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in FILES}}
        (WORK/'deployment.json').write_text(json.dumps(acceptance,indent=2))
        log('resumed',state_version=acceptance['runtime_after_resume']['state_version'])
    except Exception:
        if resume_requested:
            try:api('pause',timeout=30)
            except Exception:pass
            subprocess.run(['systemctl','--user','stop','living-kanto.service'],check=False)
            log('acceptance_failed_new_history_preserved',backup=str(backup),database=str(database))
            raise
        # Never leave an old binary paired with the new physical save format.
        subprocess.run(['systemctl','--user','stop','living-kanto.service'],check=False)
        for relative in FILES:
            target=ROOT/relative
            if (backup/relative).exists():shutil.copy2(backup/relative,target)
            else:target.unlink(missing_ok=True)
        if installed:
            for suffix in ['-wal','-shm']:Path(str(database)+suffix).unlink(missing_ok=True)
            shutil.copy2(original,database)
        subprocess.run(['systemctl','--user','start','living-kanto.service'],check=False)
        log('rolled_back_paused',backup=str(backup))
        raise


if __name__=='__main__':main()
