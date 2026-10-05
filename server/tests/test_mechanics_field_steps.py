import random
from living_kanto.mechanics import create_pokemon
from living_kanto.mechanics.field_steps import field_steps

class Fixed:
    def randrange(self,*args):return 0

def fixture():
    h={'human_id':'a','map_id':'Route1','party':['pokemon-poison']}
    p=create_pokemon('RATTATA',5,'a',random.Random(1),identifier='pokemon-poison');p['status']='tox';p['hp']=1;p['friendship']=100
    return h,[p]

def test_source_poison_fifth_step_can_faint_clear_status_and_blackout():
    h,party=fixture();original=party[0].copy()
    for _ in range(4):h,party,blackout=field_steps(h,party,Fixed());assert not blackout and party[0]['hp']==1
    h,party,blackout=field_steps(h,party,Fixed())
    assert blackout and party[0]['hp']==0 and party[0]['status']=='' and party[0]['friendship']==95
    assert original['hp']==1

def test_source_forced_tiles_friendship_count_but_skip_poison():
    h,party=fixture();h['field_steps']={'happiness':127,'poison':4};party[0]['origin_map_id']='Route1';party[0]['pokeball']='LUXURY_BALL'
    h,party,blackout=field_steps(h,party,Fixed(),forced=True)
    assert party[0]['hp']==1 and not blackout and h['field_steps']['poison']==4
    assert party[0]['friendship']==103 # source +1, Luxury+1, same region+1.
