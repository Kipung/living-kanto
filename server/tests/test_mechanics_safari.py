import random
import pytest
from living_kanto.mechanics import create_pokemon
from living_kanto.mechanics.safari import enter_safari,take_steps,start_safari_encounter,safari_turn,safari_observation
from living_kanto.mechanics.encounters import encounter_rules,select_encounter,fishing_bite

class Fixed:
    def __init__(self,values):self.values=iter(values)
    def randrange(self,*args):return next(self.values)

def fixture():
    h={'human_id':'trainer-a','money':1000,'party':[],'box':[],'pokedex':[]}
    p=create_pokemon('RHYHORN',25,None,random.Random(2),identifier='safari-rhyhorn')
    return start_safari_encounter(enter_safari(h),p),p

def test_source_admission_and_steps_are_individual_and_copy_safe():
    initial={'human_id':'a','money':500,'party':[],'box':[],'pokedex':[]}
    h=enter_safari(initial)
    assert initial['money']==500 and h['money']==0
    assert h['safari']=={'active':True,'balls':30,'steps':600,'encounter':None}
    h=take_steps(h,599);assert h['safari']['active']
    h=take_steps(h,1);assert not h['safari']['active']
    with pytest.raises(ValueError):enter_safari(dict(initial,money=499))

def test_bait_rock_are_source_factors_with_pre_action_flee():
    h,p=fixture();initial=h['safari']['encounter']['catch_factor']
    updated,p,r=safari_turn(h,p,'bait',Fixed([99,0]))
    assert updated['safari']['encounter']['catch_factor']==max(3,initial//2)
    assert updated['safari']['encounter']['bait']==1
    updated,p,r=safari_turn(updated,p,'rock',Fixed([99,0]))
    assert updated['safari']['encounter']['bait']==0
    assert updated['safari']['encounter']['rock']==1
    assert h['safari']['encounter']['bait']==0
    assert 'catch_factor' not in safari_observation(updated,p)

def test_source_capture_preserves_individual_and_full_party_boxes():
    h,p=fixture();h['party']=[f'mon-{i}' for i in range(6)]
    updated,result,r=safari_turn(h,p,'ball',Fixed([99,0,0,0,0]))
    assert r['caught'] and updated['safari']['balls']==29
    assert result['pokemon_id']==p['pokemon_id'] and result['personality']==p['personality']
    assert result['owner_id']=='trainer-a' and result['pokeball']=='SAFARI_BALL'
    assert updated['box']==[p['pokemon_id']] and len(updated['party'])==6
    assert p['owner_id'] is None

def test_last_failed_ball_ends_visit_and_storage_full_rejects():
    h,p=fixture();h['safari']['balls']=1
    updated,p,r=safari_turn(h,p,'ball',Fixed([99,65535]))
    assert r['ended'] and not updated['safari']['active']
    h,p=fixture();h['party']=['p']*6;h['box']=['b']*420
    with pytest.raises(ValueError,match='full'):safari_turn(h,p,'ball',Fixed([]))
    assert h['safari']['balls']==30

def test_reference_rod_groups_and_surf_slots():
    rules=encounter_rules()
    assert rules['fishing_mons']['groups']=={'old_rod':[0,1],'good_rod':[2,3,4],'super_rod':[5,6,7,8,9]}
    table={'water_mons':{'mons':[{'species':'SPECIES_TENTACOOL','min_level':5,'max_level':35}]*5},'fishing_mons':{'mons':[{'species':'SPECIES_MAGIKARP','min_level':i+1,'max_level':i+1} for i in range(10)]}}
    for rod,levels in [('old_rod',{1,2}),('good_rod',{3,4,5}),('super_rod',{6,7,8,9,10})]:
        assert {select_encounter([table],'fish',random.Random(i),rod=rod)['min_level'] for i in range(300)}==levels
    assert select_encounter([table],'surf',random.Random(1))['species']=='SPECIES_TENTACOOL'
    assert fishing_bite(Fixed([0])) and not fishing_bite(Fixed([1]))
