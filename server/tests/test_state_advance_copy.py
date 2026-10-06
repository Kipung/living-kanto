import copy
import pytest
from living_kanto.contracts import WorldState,ContractError
from living_kanto.contracts.base import as_plain_dict


def state():
 s=WorldState(run_id='advance-copy',state_version=3,tick=10,simulated_time=10,clock={'seconds':10},humans={'h':{'inventory':{'tea':{'quantity':1}},'memories':['private']}},world_facts={'nested':{'values':[1,2]}})
 s.state_hash=s.compute_state_hash();return s


def legacy_advance(s,changes):
 s.verify();candidate=s.apply_changes(changes);payload=as_plain_dict(candidate);payload['state_hash']='';payload['state_version']=s.state_version+1
 advanced=WorldState.from_dict(payload);advanced.state_hash=advanced.compute_state_hash();return advanced

@pytest.mark.parametrize('changes',[
 [],[{'op':'advance_clock','seconds':5}],
 [{'op':'set','path':'humans.h.inventory.tea.quantity','value':0}],
 [{'op':'set','path':'world_facts.nested.values','value':[4,5]}],
 [{'op':'append_public_event','event':{'text':'fixture'}}],
])
def test_advance_is_identical_and_independent(changes):
 s=state();original=copy.deepcopy(s.to_dict());expected=legacy_advance(s,changes);actual=s.with_advanced_version(changes)
 assert actual.to_dict()==expected.to_dict()
 actual.verify();assert actual.state_version==4
 actual.humans['h']['inventory']['tea']['quantity']=999
 actual.world_facts['nested']['values'].append(8)
 assert s.to_dict()==original;s.verify()


def test_advance_still_rejects_tampered_source():
 s=state();s.humans['h']['inventory']['tea']['quantity']=4
 with pytest.raises(ContractError,match='state_hash mismatch'):s.with_advanced_version([])
 assert s.state_version==3 and s.humans['h']['inventory']['tea']['quantity']==4


def test_failed_change_does_not_mutate_prior_state():
 s=state();before=copy.deepcopy(s.to_dict())
 with pytest.raises(ContractError):s.with_advanced_version([{'op':'set','path':'world_facts.nested.values','value':[8]},{'op':'advance_clock','seconds':True}])
 assert s.to_dict()==before;s.verify()


def test_advance_validates_new_version_bounds():
 s=state();s.state_version=2**63-1;s.state_hash=s.compute_state_hash()
 with pytest.raises(ContractError):s.with_advanced_version([])
 assert s.state_version==2**63-1;s.verify()
