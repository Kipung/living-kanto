import random
from living_kanto.mechanics.encounters import walking_encounter,select_encounter
from living_kanto.mechanics.shops import shop_catalog

class Fixed:
    def __init__(self,values):self.values=iter(values)
    def randrange(self,*args):return next(self.values)

def table(rate=100):
    return {'base_label':'sTest_FireRed','land_mons':{'encounter_rate':rate,'mons':[{'species':'SPECIES_RATTATA','min_level':5,'max_level':5}]*12}}

def trainer():return {'human_id':'a','map_id':'Route1','party':['p']}
def party():return [{'hp':20,'level':20,'ability':'RUN_AWAY','held_item':''}]

def test_source_cooldown_and_no_mutation():
    h=trainer();updated,row=walking_encounter(h,{'encounter_type':1,'behavior':2},[table(21)],party(),Fixed([0,99]))
    assert row is None and updated['field_encounter']['steps']==1 and 'field_encounter' not in h
    assert updated['field_encounter']['prev_behavior']==2

def test_source_rate_lcg_and_single_selected_level():
    updated,row=walking_encounter(trainer(),{'encounter_type':1,'behavior':2},[table()],party(),Fixed([0,0,0,0]))
    assert row=={'species':'SPECIES_RATTATA','min_level':5,'max_level':5}
    assert updated['field_encounter']['rate_rng']==12345
    assert updated['field_encounter']['steps']==0 and updated['field_encounter']['rate_buff']==0

def test_source_repel_lead_level_filter_and_steps():
    h=trainer();h['field_encounter']={'map_id':'Route1','steps':8,'rate_buff':0,'rate_rng':0,'prev_behavior':2,'repel_steps':2}
    updated,row=walking_encounter(h,{'encounter_type':1,'behavior':2},[table()],party(),Fixed([0,0]))
    assert row is None and updated['field_encounter']['repel_steps']==1
    assert h['field_encounter']['repel_steps']==2

def test_firered_slot_baseline_coexists_with_leafgreen_species():
    red=table();green=table();green['base_label']='sTest_LeafGreen';green['land_mons']['mons']=[{'species':'SPECIES_VULPIX','min_level':5,'max_level':5}]*12
    assert {select_encounter([red,green],'land',random.Random(i))['species'] for i in range(40)}=={'SPECIES_RATTATA','SPECIES_VULPIX'}
    updated,row=walking_encounter(trainer(),{'encounter_type':1,'behavior':2},[red,green],party(),Fixed([0,0,0,1,0]))
    assert row['species']=='SPECIES_VULPIX'

def test_source_regional_shop_catalogs_prices_and_tm():
    catalog=shop_catalog()
    assert len(catalog)==18
    assert catalog['CeruleanCity_Mart']['super_potion']==700
    assert catalog['CeladonCity_DepartmentStore_4F']['water_stone']==2100
    assert catalog['CeladonCity_DepartmentStore_5F']['protein']==9800
    assert 'tm05' in catalog['CeladonCity_DepartmentStore_2F']

def test_source_repel_durations_consumption_and_reusable_flutes():
    import pytest
    from living_kanto.mechanics.field_items import apply_field_item
    h={'inventory':{i:{'item_id':i,'quantity':1} for i in ('repel','super_repel','max_repel','black_flute','white_flute')}}
    for key,steps in [('repel',100),('super_repel',200),('max_repel',250)]:
        updated,event=apply_field_item(h,key)
        assert updated['field_encounter']['repel_steps']==steps and updated['inventory'][key]['quantity']==0
        with pytest.raises(ValueError,match='active'):apply_field_item(updated,'repel')
    updated,event=apply_field_item(h,'black_flute');assert updated['field_encounter']['flute']=='black'
    updated,event=apply_field_item(updated,'white_flute');assert updated['field_encounter']['flute']=='white'
    assert updated['inventory']['black_flute']['quantity']==updated['inventory']['white_flute']['quantity']==1
    assert 'field_encounter' not in h
