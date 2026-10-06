"""Unrecognized database triggers cannot silently poison committed state."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests.helpers import make_event, make_run_metadata, make_world_state
from living_kanto.store.run_store import RunStore,StoreError
import pytest


@pytest.mark.parametrize('temporary',[False,True])
def test_append_trigger_cannot_poison_private_verified_cache(tmp_path,temporary):
    store=RunStore(tmp_path/'save.db');run=store.create_run(make_run_metadata(),make_world_state())
    store.optimize_storage(run)
    _,before,head=store.load_run(run)
    event=make_event(run,event_index=before.state_version,prior_state=before,previous_head=head)
    store._db.execute("CREATE "+('TEMP ' if temporary else '')+"TRIGGER poison AFTER UPDATE OF state_json ON runs BEGIN UPDATE runs SET state_hash='bad'; END")
    with pytest.raises(StoreError,match='trigger'):
        store.append_event(event,event.transaction['state_hash'])
    assert store.load_run(run)[1].to_dict()==before.to_dict()
    assert store.event_count(run)==0
    store.close()
