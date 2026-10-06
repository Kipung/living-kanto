"""Reachable transfer candidates, rather than arbitrary nearby edge markers."""
from types import SimpleNamespace
import copy
import pytest
from living_kanto.simulation.maps import GameMap
from living_kanto.simulation.routeplanner import plan_journey, JourneyUnavailable, _routing_actor


def source_map(mid,rows,exits=None,events=None):
    m=GameMap(mid,len(rows[0]),len(rows),rows,exits or {},events=events or {})
    m.cells={(x,y):{'collision':int(v!='1'),'behavior':0,'elevation':3} for y,row in enumerate(rows) for x,v in enumerate(row)}
    return m


def test_four_nearer_unreachable_exits_do_not_hide_fifth_reachable():
    a=source_map('a',['111100001','000000001','111111111'],{(x,0):'b' for x in (0,1,2,3,8)}, {'connections':[{'direction':'up','map':'b','offset':0}]})
    b=source_map('b',['111111111']*3)
    h={'human_id':'h','map_id':'a','x':0,'y':2,'status':{},'inventory':{},'badges':[]}
    route=plan_journey({'a':a,'b':b},h,'b')
    assert route[0]['source_exit']==[8,0]
    assert route[0]['destination_map']=='b'


def test_four_blocked_transfer_landings_do_not_hide_fifth_legal():
    a=source_map('a',['11111']*2,{(x,0):'b' for x in range(5)}, {'connections':[{'direction':'up','map':'b','offset':0}]})
    b=source_map('b',['11111']*2)
    h={'human_id':'h','map_id':'a','x':0,'y':1,'status':{},'inventory':{},'badges':[]}
    state=SimpleNamespace(humans={str(x):{'human_id':str(x),'map_id':'b','x':x,'y':1} for x in range(4)},npcs={},pokemon={})
    route=plan_journey({'a':a,'b':b},h,'b',state=state)
    assert route[0]['source_exit']==[4,0]
    assert route[0]['destination']==[4,1]


def test_candidate_scan_preserves_gate_and_search_limits():
    a=source_map('a',['11111']*2,{(x,0):'Route23' for x in range(5)}, {'connections':[{'direction':'up','map':'Route23','offset':0}]})
    b=source_map('Route23',['11111']*2)
    h={'human_id':'h','map_id':'a','x':0,'y':1,'status':{},'inventory':{},'badges':[]}
    with pytest.raises(JourneyUnavailable):plan_journey({'a':a,'Route23':b},h,'Route23')
    h['badges']=['boulder','cascade','thunder','rainbow','soul','marsh','volcano','earth']
    with pytest.raises(JourneyUnavailable):plan_journey({'a':a,'Route23':b},h,'Route23',max_tiles=1)
    with pytest.raises(JourneyUnavailable):plan_journey({'a':a,'Route23':b},h,'Route23',max_nodes=1)


def test_forced_tile_path_is_preserved_and_actor_remains_private_and_unchanged():
    a=source_map('a',['11111'],{(4,0):'b'},{'connections':[{'direction':'right','map':'b','offset':0}]})
    a.source_revision='declared-test';a.cells[(1,0)]['behavior']=0x54;a.cells[(4,0)]['behavior']=0x58
    b=source_map('b',['11111'])
    h={'human_id':'h','map_id':'a','x':0,'y':0,'status':{},'inventory':{},'badges':[],'individual_life':{'private_commitment':'unrelated'},'field':{'private_switches':['retained']}}
    before=copy.deepcopy(h)
    route=plan_journey({'a':a,'b':b},h,'b')
    assert route[0]['steps']==[[1,0],[2,0],[3,0],[4,0]]
    assert h==before
    assert 'individual_life' not in _routing_actor(h)
    assert _routing_actor(h)['field']==h['field']
