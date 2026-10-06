"""Bounded, private local inference audit; never part of a person's observation."""
from pathlib import Path
import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


class InferenceTrace:
    def __init__(self, directory, run_id, max_bytes=64 * 1024 * 1024, max_records=2000):
        if max_bytes < 1024 or max_records < 1:
            raise ValueError('Invalid inference audit bounds')
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Hash the run identifier so it cannot escape the supplied directory.
        self.path = directory / (hashlib.sha256(run_id.encode()).hexdigest()[:24] + '.sqlite3')
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        self.run_id, self.max_bytes, self.max_records = run_id, max_bytes, max_records
        self.lock = threading.Lock()
        self.audit_error = None
        with self._connect() as db:
            db.execute('PRAGMA auto_vacuum=FULL')
            db.execute('CREATE TABLE IF NOT EXISTS traces (id TEXT PRIMARY KEY, actor TEXT, observation_hash TEXT, response_hash TEXT, created REAL, body TEXT, size INTEGER)')

    def _connect(self):
        return sqlite3.connect(str(self.path), timeout=10)

    def append(self, record):
        record = {**record, 'trace_id': uuid.uuid4().hex, 'run_id': self.run_id, 'created_at': time.time()}
        body = json.dumps(record, ensure_ascii=False, separators=(',', ':'))
        size = len(body.encode())
        if size > self.max_bytes:
            raise ValueError('Inference trace exceeds audit byte budget')
        with self.lock, self._connect() as db:
            db.execute('INSERT INTO traces VALUES (?,?,?,?,?,?,?)', (record['trace_id'], record.get('human_id'), record.get('observation_hash'), record.get('response_hash'), record['created_at'], body, size))
            while True:
                count, total = db.execute('SELECT COUNT(*), COALESCE(SUM(size),0) FROM traces').fetchone()
                if count <= self.max_records and total <= self.max_bytes:
                    break
                db.execute('DELETE FROM traces WHERE id=(SELECT id FROM traces ORDER BY created,id LIMIT 1)')
        return record['trace_id']

    def outcome(self, actor, observation_hash, response_hash, outcome, event_id=None, reason=None, state_version=None):
        if outcome not in {'accepted', 'engine_rejected', 'stale', 'discarded', 'cancelled'}:
            raise ValueError('Invalid inference outcome')
        with self.lock, self._connect() as db:
            row = db.execute('SELECT id,body FROM traces WHERE actor=? AND observation_hash=? AND response_hash=? ORDER BY created DESC LIMIT 1', (actor, observation_hash, response_hash)).fetchone()
            if not row:
                return False
            record = json.loads(row[1]); record['outcome'] = outcome
            record['event_id'] = event_id
            record['state_version'] = state_version
            # Reasons supplied by engine must be safe fixed diagnostics.
            record['outcome_reason'] = str(reason)[:500] if reason is not None else None
            body = json.dumps(record, ensure_ascii=False, separators=(',', ':'))
            db.execute('UPDATE traces SET body=?,size=? WHERE id=?', (body, len(body.encode()), row[0]))
            while db.execute('SELECT COALESCE(SUM(size),0) FROM traces').fetchone()[0] > self.max_bytes:
                db.execute('DELETE FROM traces WHERE id=(SELECT id FROM traces ORDER BY created,id LIMIT 1)')
            return True

    def records(self, actor=None, limit=100):
        with self.lock, self._connect() as db:
            if actor is None:
                rows = db.execute('SELECT body FROM traces ORDER BY created DESC LIMIT ?', (min(max(1, limit), self.max_records),)).fetchall()
            else:
                rows = db.execute('SELECT body FROM traces WHERE actor=? ORDER BY created DESC LIMIT ?', (actor, min(max(1, limit), self.max_records))).fetchall()
        return [json.loads(row[0]) for row in rows]

    def status(self):
        with self.lock, self._connect() as db:
            count, size = db.execute('SELECT COUNT(*),COALESCE(SUM(size),0) FROM traces').fetchone()
        return {'enabled': True, 'records': count, 'retained_bytes': size, 'max_records': self.max_records,
                'max_bytes': self.max_bytes, 'audit_error': self.audit_error}

    def list_records(self, human_id, limit=100, before_id=None):
        with self.lock, self._connect() as db:
            boundary = None
            if before_id:
                boundary = db.execute('SELECT created FROM traces WHERE id=? AND actor=?', (before_id, human_id)).fetchone()
                if boundary is None:
                    return []
            query = 'SELECT body FROM traces WHERE actor=?'
            values = [human_id]
            if boundary:
                query += ' AND (created < ? OR (created=? AND id < ?))'
                values.extend([boundary[0], boundary[0], before_id])
            query += ' ORDER BY created DESC,id DESC LIMIT ?'
            values.append(min(max(1, limit), self.max_records))
            rows = db.execute(query, values).fetchall()
        return [json.loads(row[0]) for row in rows]

    def get_record(self, trace_id):
        with self.lock, self._connect() as db:
            row = db.execute('SELECT body FROM traces WHERE id=?', (trace_id,)).fetchone()
        return json.loads(row[0]) if row else None
