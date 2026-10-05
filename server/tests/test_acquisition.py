import copy,random
import pytest
from living_kanto.mechanics.acquisition import acquisition_actions,acquisition_effects,transition_acquisition,source_catalog,AcquisitionError,LAB

def trainer(mid,x,y):return {'human_id':'h','map_id':mid,'x':x,'y':y,'money':200000,'party':[],'box':[],'pokedex':[],'inventory':{}}
def apply(h,action,args):return acquisition_effects(h,action,args,random.Random(7))
def test_actual_miguel_required_and_choice_once_then_consumed_revival():
    h=trainer('MtMoon_B2F',13,7)
    with pytest.raises(AcquisitionError):apply(h,'choose_fossil',{'fossil':'DOME_FOSSIL'})
    h['access']={'fossil_researcher_defeated':True};h,_,_=apply(h,'choose_fossil',{'fossil':'DOME_FOSSIL'})
    assert h['inventory']['DOME_FOSSIL']['quantity']==1
    h['x']=14
    with pytest.raises(AcquisitionError):apply(h,'choose_fossil',{'fossil':'HELIX_FOSSIL'})
    h.update(map_id=LAB,x=12,y=4);h,_,_=apply(h,'submit_fossil',{'fossil':'DOME_FOSSIL'})
    assert h['inventory']['DOME_FOSSIL']['quantity']==0
    with pytest.raises(AcquisitionError):apply(h,'collect_revived_fossil',{})
    h['acquisition']=transition_acquisition(h,LAB,'CinnabarIsland_PokemonLab_Entrance');h,mon,receipt=apply(h,'collect_revived_fossil',{})
    assert (mon['species'],mon['level'],mon['original_trainer_id'])==('KABUTO',5,'h')
    assert not h['acquisition'].get('reviving') and receipt['source_sha256']

def test_source_coins_capped_and_porygon_firered_cost_level():
    h=trainer('CeladonCity_Restaurant',1,3);h,_,_=apply(h,'acquire_key_gift',{'gift_id':'coin_case'})
    h.update(map_id='CeladonCity_GameCorner',x=6,y=3)
    for _ in range(19):h,_,_=apply(h,'buy_coins',{'amount':500})
    for _ in range(9):h,_,_=apply(h,'buy_coins',{'amount':50})
    assert h['acquisition']['coins']==9950
    with pytest.raises(AcquisitionError):apply(h,'buy_coins',{'amount':50})
    # Explicit final-remainder mechanical adaptation preserves original exchange rate.
    h,_,receipt=apply(h,'buy_coins',{'amount':49})
    assert h['acquisition']['coins']==9999 and h['money']==20
    assert 'final sub-50' in receipt['adaptation']
    h.update(map_id='CeladonCity_GameCorner_PrizeRoom',x=4,y=3)
    h,mon,_=apply(h,'redeem_prize',{'species':'PORYGON'})
    assert (mon['species'],mon['level'])==('PORYGON',26) and h['acquisition']['coins']==0

def test_lapras_original_source_gift_and_claim():
    from living_kanto.mechanics.source_gifts import receive_gift
    h=trainer('SilphCo_7F',0,8);h,p=receive_gift(h,'lapras',random.Random(4))
    assert (p['species'],p['level'])==('LAPRAS',25)
    with pytest.raises(ValueError):receive_gift(h,'lapras',random.Random(4))
