import copy
from types import SimpleNamespace
import pytest
from living_kanto.simulation.maps import GameMap
from living_kanto.simulation.routeplanner import _routing_actor,plan_journey,JourneyUnavailable


def road(mid,target=None):
 return GameMap(mid,5,3,['11111']*3,{(4,1):target} if target else {},events={'connections':[{'direction':'right','map':target,'offset':0}]} if target else {})


def test_routing_copy_retains_all_mechanical_and_unknown_fields():
 h={'human_id':'h','map_id':'a','x':1,'y':1,'facing':'south','inventory':{},'access':{},'badges':[],'party':[],'safari':{},'status':{},'field':{},'future_mechanic':{'enabled':True},'memories':['private']}
 reduced=_routing_actor(h)
 assert reduced=={k:v for k,v in h.items() if k!='memories'}
 assert h['memories']==['private']


def test_private_history_is_never_copied_by_route_search():
 class History:
  def __deepcopy__(self,memo):raise AssertionError('Route search copied private history')
 h={'human_id':'h','map_id':'a','x':1,'y':1,'inventory':{},'badges':[],'status':{},'memories':History(),'last_decision':History()}
 assert plan_journey({'a':road('a','b'),'b':road('b')},h,'b')


def test_tea_is_consumed_in_route_preview_without_mutating_original():
 maps={'Route5_SouthEntrance':road('Route5_SouthEntrance','SaffronCity'),'SaffronCity':road('SaffronCity','c'),'c':road('c')}
 h={'human_id':'h','map_id':'Route5_SouthEntrance','x':1,'y':1,'inventory':{'tea':{'quantity':1}},'badges':[],'status':{},'field':{},'memories':['private']}
 original=copy.deepcopy(h);route=plan_journey(maps,h,'c')
 changes=route[0]['checkpoint_changes']
 assert any(c['path'].endswith('.access.saffron_tea') and c['value'] is True for c in changes)
 assert next(c['value'] for c in changes if c['path'].endswith('.inventory'))['tea']['quantity']==0
 assert h==original
 h['inventory']['tea']['quantity']=0
 with pytest.raises(JourneyUnavailable):plan_journey(maps,h,'c')


def test_private_switch_changes_traversal_and_preview_retains_status():
 a=road('a','b');a.events['strength_switches']=[{'id':'bridge','barriers':[{'x':2,'y':y} for y in range(3)]}]
 maps={'a':a,'b':road('b')}
 h={'human_id':'h','map_id':'a','x':1,'y':1,'inventory':{},'badges':[],'status':{'surfing':False},'field':{'switches':[]},'memories':['private']}
 with pytest.raises(JourneyUnavailable):plan_journey(maps,h,'b')
 h['field']['switches']=['bridge'];route=plan_journey(maps,h,'b')
 assert route[0]['field_after']['switches']==['bridge']
 assert route[0]['status_after']['surfing'] is False
