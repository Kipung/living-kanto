"""Care facts are private, read-only, and never substitute a human decision."""
import copy
import json
from types import SimpleNamespace
from living_kanto.contracts.human import LegalAction
from living_kanto.simulation import care
from living_kanto.simulation.maps import GameMap
from living_kanto.simulation.services import ServiceMixin
from test_gameplay import game


class Engine(ServiceMixin):
    def __init__(self, maps):
        self.maps = maps


def fixture():
    names = ['A_PokemonCenter_1F', 'B_PokemonCenter_1F', 'C_PokemonCenter_1F', 'D_PokemonCenter_1F']
    points = [(1,1), (5,3), (3,3), (4,1)]
    warps = [{'x':x,'y':y,'dest_map':name,'dest_warp_id':0} for name,(x,y) in zip(names,points)]
    home = GameMap('Home',7,5,['0000000','0101110','0001110','0001110','0000000'],dict(zip(points,names)),events={'warp_events':warps})
    maps = {'Home':home}
    for name in names:
        maps[name] = GameMap(name,3,3,['111']*3,{(1,1):'Home'},events={'warp_events':[{'x':1,'y':1,'dest_map':'Home','dest_warp_id':0}]})
    human = {'human_id':'a','map_id':'Home','x':3,'y':2,'party':['p'],'box':[],
             'inventory':{},'status':{},'memories':{},'goal':{},'money':3000}
    mon = {'pokemon_id':'p','owner_id':'a','hp':4,'stats':{'hp':20},'status':'psn',
           'moves':[{'move':'TACKLE','pp':0,'max_pp':35}]}
    state = SimpleNamespace(humans={'a':human},pokemon={'p':mon},simulated_time=50,world_facts={},npcs={})
    return Engine(maps),state


def test_own_condition_factual_and_old_save_untouched():
    engine,state = fixture();before = copy.deepcopy(state.__dict__)
    options = [LegalAction('wait'),LegalAction('journey_to',{'map_id':'B_PokemonCenter_1F'})]
    view = care.observation_view(engine,state,'a',[state.pokemon['p']],options)
    assert view['needs_care'] and view['injured_count']==1 and view['status_count']==1 and view['pp_depleted_count']==1
    assert view['party_members'][0]['depleted_pp_moves']==['TACKLE']
    assert view['healing_routes_visible']==['B_PokemonCenter_1F'] and not view['heal_option_visible']
    assert 'service_duty' not in view and 'local_center' not in view
    assert state.__dict__==before


def test_local_center_public_counts_own_queue_and_legacy_duty_private():
    engine,state = fixture();mid='B_PokemonCenter_1F';state.humans['a']['map_id']=mid
    nurse={'human_id':'n','map_id':mid,'x':0,'y':0,'role':'service_staff','service_assignment':{'kind':'healing','map_id':mid},
           'memories':{'secret':'PRIVATE MEMORY'},'goal':{'text':'PRIVATE GOAL'},'party':['secret-mon'],'ready_at':100}
    state.humans['n']=nurse
    state.pokemon['secret-mon']={'hp':1,'moves':['PRIVATE MOVE']}
    state.world_facts['service_queues']={mid:[{'human_id':'n','request_id':'first'}, {'human_id':'a','request_id':'own'}]}
    before=copy.deepcopy(state.__dict__)
    view=care.observation_view(engine,state,'a',[state.pokemon['p']],[LegalAction('heal_party')])
    assert view['local_center']=={'map_id':mid,'waiting_customers':2,'own_queue_position':2,'local_staff_count':1,'ready_staff_count':0,'service_requires_staff_choice':True}
    assert view['heal_option_visible']
    assert 'PRIVATE' not in json.dumps(view) and 'secret-mon' not in json.dumps(view)
    own=care.observation_view(engine,state,'n',[],[LegalAction('serve_customer')])
    assert own['service_duty']['serve_option_visible'] and own['service_duty']['at_assigned_station']
    assert own['service_duty']['waiting_customers']==2 and 'workplace' not in nurse
    assert state.__dict__==before


def test_routes_use_real_reachability_then_actual_cost_and_keep_state():
    engine,state=fixture();before=copy.deepcopy(state.__dict__)
    options=care.route_actions(engine,state,'a')
    # A is geometrically near but disconnected. C and D beat B by actual path.
    assert [option.arguments['map_id'] for option in options]==['C_PokemonCenter_1F','D_PokemonCenter_1F']
    assert all(option.action=='journey_to' and option.known_consequences['destination_kind']=='healing' for option in options)
    assert state.__dict__==before and state.pokemon['p']['hp']==4
    # Dynamic occupancy at the exact arrival tile removes that Center option.
    state.humans['blocker']={'human_id':'blocker','map_id':'C_PokemonCenter_1F','x':1,'y':1}
    assert [option.arguments['map_id'] for option in care.route_actions(engine,state,'a')]==['D_PokemonCenter_1F','B_PokemonCenter_1F']


def test_no_routes_healthy_busy_battle_or_fast_validation():
    engine,state=fixture()
    assert not care.route_actions(engine,state,'a',include_routes=False)
    for key in ('battle_id','service_request','activity','movement_intent'):
        state.humans['a'][key]={'busy':True}
        assert not care.route_actions(engine,state,'a')
        state.humans['a'].pop(key)
    state.humans['a']['ready_at']=51
    assert not care.route_actions(engine,state,'a')
    state.humans['a'].pop('ready_at')
    state.pokemon['p'].update(hp=20,status='',moves=[{'move':'TACKLE','pp':35,'max_pp':35}])
    assert not care.route_actions(engine,state,'a')


def test_legacy_staff_return_option_no_teleport_or_choice_replacement():
    engine,state=fixture();human=state.humans['a']
    human['service_assignment']={'kind':'healing','map_id':'B_PokemonCenter_1F'}
    state.pokemon['p'].update(hp=20,status='',moves=[])
    before=copy.deepcopy(state.__dict__)
    options=care.route_actions(engine,state,'a')
    assert len(options)==1 and options[0].arguments=={'map_id':'B_PokemonCenter_1F'}
    assert options[0].known_consequences['destination_kind']=='workplace'
    assert state.__dict__==before and human['map_id']=='Home'
    duty=care.observation_view(engine,state,'a',[state.pokemon['p']],options)['service_duty']
    assert not duty['at_assigned_station'] and 'waiting_customers' not in duty


def test_crowded_physical_pc_preserves_healing_and_staff_choice(game):
    import random
    from living_kanto.mechanics import create_pokemon
    from test_gameplay import state
    from test_mechanics_storage_gameplay import pc
    engine,_=game;current=state(game);hid='human-001'
    mid,position,facing=pc(game);human=current.humans[hid]
    human.update(map_id=mid,x=position[0],y=position[1],facing=facing,party=[],box=[])
    for index in range(31):
        mon=create_pokemon('RATTATA',5,hid,random.Random(index),identifier=f'care-crowd-{index}')
        current.pokemon[mon['pokemon_id']]=mon
        human['party' if index==0 else 'box'].append(mon['pokemon_id'])
    current.pokemon['care-crowd-0']['hp']=1
    human['pc_storage']={'selected_pokemon':'care-crowd-1'}
    # Explicit dense-crowd fixture, preserving the engine's normal menus.
    for other in list(current.humans.values())[1:65]:
        other.update(map_id=mid,x=position[0],y=position[1],party=[])
    before=copy.deepcopy(current.to_dict())
    options=engine.legal_actions(current,hid)
    assert len(options)<=128 and any(option.action=='heal_party' for option in options)
    assert any(option.action=='talk_to' for option in options) and any(option.action=='store_withdraw' for option in options)
    assert current.to_dict()==before and current.pokemon['care-crowd-0']['hp']==1
    nurse=next(actor for actor,worker in current.humans.items() if worker.get('service_assignment',{}).get('map_id')==mid)
    current.world_facts['service_queues']={mid:[{'request_id':'care-crowd-q','human_id':hid,'map_id':mid,'kind':'healing','arguments':{},'reserved_payment':0,'requested_at':current.simulated_time}]}
    # Service staff must be at the source counter even in a dense PC fixture.
    post=current.humans[nurse]['workplace']['service_post']
    current.humans[nurse].update(x=post['x'],y=post['y'],facing='south')
    nurse_options=engine.legal_actions(current,nurse)
    assert any(option.action=='serve_customer' for option in nurse_options)
    assert any(option.action=='rest' for option in nurse_options)
