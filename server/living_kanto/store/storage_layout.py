"""Lossless, versioned physical storage; canonical simulation contracts stay v1."""
import json
import zlib

from living_kanto.contracts.base import canonical_json

MAGIC = b'LKZ2'
DOMAINS = ('humans', 'pokemon', 'npcs', 'maps', 'items', 'economies', 'factions')
MARKER = '__lk_archived_memories_v2__'
SCHEMA = """
CREATE TABLE IF NOT EXISTS storage_records (
 run_id TEXT NOT NULL, domain TEXT NOT NULL, entity_id TEXT NOT NULL, payload BLOB NOT NULL,
 PRIMARY KEY(run_id,domain,entity_id), FOREIGN KEY(run_id) REFERENCES runs(run_id));
CREATE TABLE IF NOT EXISTS storage_archive (
 run_id TEXT NOT NULL, kind TEXT NOT NULL, owner_id TEXT NOT NULL, entry_id TEXT NOT NULL, payload BLOB NOT NULL,
 PRIMARY KEY(run_id,kind,owner_id,entry_id), FOREIGN KEY(run_id) REFERENCES runs(run_id));
CREATE TABLE IF NOT EXISTS storage_checkpoints (
 run_id TEXT NOT NULL, state_version INTEGER NOT NULL, head_hash TEXT NOT NULL,
 state_hash TEXT NOT NULL, prefix_digest TEXT NOT NULL, state_blob BLOB NOT NULL,
 PRIMARY KEY(run_id,state_version), FOREIGN KEY(run_id) REFERENCES runs(run_id));
"""


def pack(value):
    return MAGIC + zlib.compress(canonical_json(value).encode('utf-8'), 6)


def unpack(value):
    if isinstance(value, bytes):
        if not value.startswith(MAGIC):
            raise ValueError('Unknown storage payload version')
        value = zlib.decompress(value[len(MAGIC):]).decode('utf-8')
    return json.loads(value)


def header(state):
    doc = state.to_dict()
    for domain in DOMAINS:
        doc.pop(domain)
    doc['kind'] = 'living-kanto-storage-v2'
    facts = dict(doc['world_facts'])
    if isinstance(facts.get('battles'), dict):
        facts.pop('battles')
        doc['archived_battles'] = True
    doc['world_facts'] = facts
    return doc


def read_state(db, row):
    if row['storage_version'] == 1:
        return json.loads(row['state_json'])
    if row['storage_version'] != 2:
        raise ValueError('Unsupported save storage version')
    doc = json.loads(row['state_json'])
    if doc.pop('kind') != 'living-kanto-storage-v2':
        raise ValueError('Invalid storage header')
    doc['kind'] = 'world_state'
    for domain in DOMAINS:
        doc[domain] = {}
    for record in db.execute('SELECT domain,entity_id,payload FROM storage_records WHERE run_id=?', (row['run_id'],)):
        if record['domain'] not in DOMAINS:
            raise ValueError('Unknown state record domain')
        doc[record['domain']][record['entity_id']] = unpack(record['payload'])
    for human in doc['humans'].values():
        if human.pop(MARKER, False):
            human['memories'] = {}
    if doc.pop('archived_battles', False):
        doc['world_facts']['battles'] = {}
    for record in db.execute('SELECT kind,owner_id,entry_id,payload FROM storage_archive WHERE run_id=?', (row['run_id'],)):
        if record['kind'] == 'memory':
            doc['humans'][record['owner_id']]['memories'][record['entry_id']] = unpack(record['payload'])
        elif record['kind'] == 'battle':
            doc['world_facts']['battles'][record['entry_id']] = unpack(record['payload'])
        else:
            raise ValueError('Unknown archive record kind')
    return doc


def _sync_archive(db, run_id, kind, owner, old, new):
    for key in old.keys() - new.keys():
        db.execute('DELETE FROM storage_archive WHERE run_id=? AND kind=? AND owner_id=? AND entry_id=?', (run_id,kind,owner,key))
    for key, value in new.items():
        if key not in old or old[key] != value:
            db.execute('INSERT OR REPLACE INTO storage_archive VALUES (?,?,?,?,?)', (run_id,kind,owner,key,pack(value)))


def write_records(db, state, prior=None, changes=None):
    """Only touched entities are considered; unchanged archive entries never rewrite."""
    run_id = state.run_id
    for domain in DOMAINS:
        new = getattr(state, domain)
        old = getattr(prior, domain) if prior is not None else {}
        keys = old.keys() | new.keys() if changes is None else {
            c['path'].split('.')[1] for c in changes
            if c.get('path', '').split('.')[0] == domain
        }
        for key in keys:
            if key not in new:
                db.execute('DELETE FROM storage_records WHERE run_id=? AND domain=? AND entity_id=?', (run_id,domain,key))
                if domain == 'humans':
                    db.execute("DELETE FROM storage_archive WHERE run_id=? AND kind='memory' AND owner_id=?", (run_id,key))
                continue
            value = dict(new[key])
            before = dict(old.get(key, {}))
            if domain == 'humans':
                if MARKER in value:
                    raise ValueError('Reserved storage marker in human record')
                memories = value.get('memories')
                old_memories = before.get('memories')
                if isinstance(memories, dict):
                    value.pop('memories')
                    value[MARKER] = True
                if isinstance(old_memories, dict):
                    before.pop('memories')
                    before[MARKER] = True
                _sync_archive(db,run_id,'memory',key,
                              old_memories if isinstance(old_memories,dict) else {},
                              memories if isinstance(memories,dict) else {})
            if key not in old or value != before:
                db.execute('INSERT OR REPLACE INTO storage_records VALUES (?,?,?,?)', (run_id,domain,key,pack(value)))
    if changes is None or any(c.get('path','').startswith('world_facts.battles') for c in changes):
        old = prior.world_facts.get('battles', {}) if prior else {}
        new = state.world_facts.get('battles', {})
        _sync_archive(db,run_id,'battle','',old if isinstance(old,dict) else {},new if isinstance(new,dict) else {})
