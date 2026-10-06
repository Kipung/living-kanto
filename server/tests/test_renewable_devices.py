import copy
import random
from types import SimpleNamespace
import pytest
from living_kanto.mechanics.renewable_items import catalog, renewable_flags, available, regenerate_on_entry
from living_kanto.mechanics.field_steps import field_steps
from living_kanto.mechanics.utility_items import use_town_map, use_teachy_tv, teachy_topics, use_powder_jar
from living_kanto.mechanics.item_rules import ItemError
from living_kanto.mechanics.acquisition import source_catalog, acquisition_effects, acquisition_actions, AcquisitionError
from living_kanto.simulation.hidden_items import collect
from living_kanto.simulation.entity_systems import map_visit_changes
from test_gameplay import game,act,scenario,state,locate


class Draws:
    def __init__(self,draw):self.draw=draw;self.calls=0
    def randrange(self,n):assert n==65536;self.calls+=1;return self.draw


def actor(**extra):
    return {'human_id':'a','map_id':'Route20','x':1,'y':1,'party':[],
            'inventory':{},'field_steps':{'renewable':1500},**extra}


def test_source_renewables_initially_unavailable_and_counter_saturates():
    rule=catalog();assert rule['threshold']==1500 and len(rule['groups'])==15
    assert len(renewable_flags())==61
    assert not available(actor(), 'FLAG_HIDDEN_ITEM_ROUTE20_STARDUST')
    assert available(actor(), 'FLAG_HIDDEN_ITEM_ROUTE10_SUPER_POTION')
    h=actor(field_steps={})
    for _ in range(1501):h,_,_=field_steps(h,[],random.Random(1))
    assert h['field_steps']['walked']==1501 and h['field_steps']['renewable']==1500


@pytest.mark.parametrize('draw,rarity',[(59,'common'),(60,'uncommon'),(89,'uncommon'),(90,'rare'),(99,'rare'),(65535,'common')])
def test_source_sampling_thresholds_all_groups_full_reset_per_trainer(draw,rarity):
    h=actor(collected_hidden_items=list(renewable_flags())+['FLAG_ORDINARY'],
            renewable_hidden_items={'generation':2,'available_flags':list(renewable_flags())})
    before=copy.deepcopy(h);rng=Draws(draw);updated,receipt=regenerate_on_entry(h,rng)
    expected={flag for group in catalog()['groups'] for flag in group[rarity]}
    assert set(updated['renewable_hidden_items']['available_flags'])==expected
    assert rng.calls==15 and updated['field_steps']['renewable']==0 and updated['renewable_hidden_items']['generation']==3
    assert updated['collected_hidden_items']==['FLAG_ORDINARY'] and h==before
    assert not any(flag in str(receipt) for flag in renewable_flags())


def test_regeneration_requires_eligible_entry_threshold_and_recollection():
    rng=Draws(60)
    assert regenerate_on_entry(actor(map_id='PalletTown'),rng)[1] is None and rng.calls==0
    assert regenerate_on_entry(actor(field_steps={'renewable':1499}),rng)[1] is None
    updated,_=regenerate_on_entry(actor(),rng)
    row={'flag':'FLAG_HIDDEN_ITEM_ROUTE20_STARDUST','item':'ITEM_STARDUST','quantity':1}
    updated=collect(updated,row)
    assert updated['inventory']['stardust']['quantity']==1
    with pytest.raises(ItemError):collect(updated,row)
    updated['field_steps']['renewable']=1500
    updated,_=regenerate_on_entry(updated,Draws(60))
    updated=collect(updated,row);assert updated['inventory']['stardust']['quantity']==2


def test_map_hook_prospective_step_counts_full_entity_and_same_map_guard():
    h=actor(map_id='PalletTown',field_steps={'renewable':1499},map_visit=8)
    s=SimpleNamespace(humans={'a':h},world_facts={'seed':4},state_version=20)
    changes=[{'op':'set','path':'humans.a.map_id','value':'Route20'},
             {'op':'set','path':'humans.a.field_steps.renewable','value':1500}]
    extra=map_visit_changes(s,changes)
    assert any(c['path']=='humans.a.field_steps' and c['value']['renewable']==0 for c in extra)
    assert any(c['path']=='humans.a.map_visit' and c['value']==9 for c in extra)
    assert extra==map_visit_changes(s,changes)
    replacement={**h,'map_id':'Route20','field_steps':{'renewable':1500}}
    full=map_visit_changes(s,[{'op':'set','path':'humans.a','value':replacement}])
    assert any(c['path']=='humans.a.renewable_hidden_items' for c in full)
    assert not map_visit_changes(s,[{'op':'set','path':'humans.a.field_steps.renewable','value':1500}])
    assert h['field_steps']['renewable']==1499


def test_town_map_teachy_topics_and_powder_read_own_state_no_rewards():
    h=actor(map_id='PalletTown',inventory={'town_map':{'quantity':1},'teachy_tv':{'quantity':1},'powder_jar':{'quantity':1}})
    before=copy.deepcopy(h);updated,mapview=use_town_map(h,{'PalletTown':None,'Route1':None,'ViridianCity':None})
    assert mapview['you']['map_id']=='PalletTown' and any(r['name']=='PALLET TOWN' for r in mapview['locations'])
    assert any(r['visited'] for r in mapview['locations']) and h==before and updated['inventory']==h['inventory']
    assert teachy_topics(h)==('battle','status','matchups','catching')
    updated,lesson=use_teachy_tv(h,'catching');assert 'wild' in lesson['lesson'] and 'catching' in updated['utility_items']['teachy_topics']
    with pytest.raises(ItemError):use_teachy_tv(h,'tms')
    h['inventory']['tm_case']={'quantity':1}
    assert len(teachy_topics(h))==6 and use_teachy_tv(h,'register')[1]['title']=='How do I register an item?'
    assert use_powder_jar(h)[1]['berry_powder']==0
    h['acquisition']={'berry_powder':1234};updated,jar=use_powder_jar(h)
    assert jar['berry_powder']==1234 and updated['acquisition']==h['acquisition']
    h['acquisition']['berry_powder']=100000
    with pytest.raises(ItemError):use_powder_jar(h)


@pytest.mark.parametrize('gift',['town_map','teachy_tv','powder_jar'])
def test_device_gifts_source_positions_prerequisites_and_claim_once(gift):
    station=source_catalog()['stations'][gift]
    h=actor(map_id=station['map_id'],x=station['x'],y=station['y']+1)
    assert not any(a.arguments=={'gift_id':gift} for a in acquisition_actions(h))
    if gift=='powder_jar':h['inventory']['berry_pouch']={'quantity':1}
    else:h['party']=['starter']
    updated,p,_=acquisition_effects(h,'acquire_key_gift',{'gift_id':gift},random.Random(1))
    assert p is None and updated['inventory'][gift.upper()]['quantity']==1
    with pytest.raises(AcquisitionError):acquisition_effects(updated,'acquire_key_gift',{'gift_id':gift},random.Random(1))


def test_devices_actual_engine_views_and_replay(game):
    engine,store=game;hid='human-001'
    scenario(game,[{'op':'set','path':f'humans.{hid}.inventory.{item}','value':{'quantity':1}} for item in ('town_map','teachy_tv','powder_jar')])
    before=state(game)
    after=act(game,hid,'use_field_item',{'item':'town_map'})
    assert after.humans[hid]['last_town_map']['you']['map_id']==before.humans[hid]['map_id']
    after=act(game,hid,'use_field_item',{'item':'teachy_tv','topic':'battle'})
    after=act(game,hid,'use_field_item',{'item':'powder_jar'})
    assert after.pokemon==before.pokemon and after.humans[hid]['inventory']==before.humans[hid]['inventory']
    assert after.humans[hid]['last_powder_jar']['berry_powder']==0
    assert store.replay('gameplay-test').state_hash==after.state_hash
