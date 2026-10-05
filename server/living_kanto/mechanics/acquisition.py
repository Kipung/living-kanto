"""Source physical acquisition; NPC dialogue becomes explicit mechanical stations.

No trainer victory is created. Fossil choice requires a recorded actual Miguel win.
Cartridge global flags become per-trainer claims; no Creative permission is implied.
"""
import copy,hashlib,json,re
from functools import lru_cache
from .reference import REFERENCE
from .pokemon import create_pokemon
from ..contracts.human import LegalAction
LAB='CinnabarIsland_PokemonLab_ExperimentRoom'
FOSSILS={'HELIX_FOSSIL':'OMANYTE','DOME_FOSSIL':'KABUTO','OLD_AMBER':'AERODACTYL'}
class AcquisitionError(ValueError):pass
@lru_cache(maxsize=1)
def source_catalog():
    stations={};sources={}
    def station(mid,suffix):
        directory=REFERENCE/'data/maps'/mid
        for name in ['map.json','scripts.inc']:
            file=directory/name;sources[str(file.relative_to(REFERENCE))]=hashlib.sha256(file.read_bytes()).hexdigest()
        obj=next(o for o in json.loads((directory/'map.json').read_text())['object_events'] if o['script'].endswith(suffix))
        return {'map_id':mid,'x':obj['x'],'y':obj['y'],'script':obj['script']}
    stations['helix']=station('MtMoon_B2F','_HelixFossil');stations['dome']=station('MtMoon_B2F','_DomeFossil')
    stations['old_amber']=station('PewterCity_Museum_1F','_OldAmberScientist')
    stations['coin_case']=station('CeladonCity_Restaurant','_CoinCaseMan')
    stations['laboratory']=station(LAB,'_FossilScientist')
    stations['coins']=station('CeladonCity_GameCorner','_CoinsClerk')
    stations['prizes']=station('CeladonCity_GameCorner_PrizeRoom','_PrizeClerkMons')
    entrance=REFERENCE/'data/maps/CinnabarIsland_PokemonLab_Entrance/scripts.inc'
    sources[str(entrance.relative_to(REFERENCE))]=hashlib.sha256(entrance.read_bytes()).hexdigest()
    script=(REFERENCE/'data/maps/CeladonCity_GameCorner_PrizeRoom/scripts.inc').read_text()
    prizes={}
    for label,species,give in [('Abra','ABRA','Abra'),('Clefairy','CLEFAIRY','Clefairy'),('DratiniPinsir','DRATINI','Dratini'),('ScytherDratini','SCYTHER','Scyther'),('Porygon','PORYGON','Porygon')]:
        block=script.split('EventScript_'+label+'::')[1].split('\n\n')[0]
        cost=int(re.search(r'setvar VAR_TEMP_2, (\d+)',block).group(1))
        block=script.split('EventScript_Give'+give+'::')[1].split('\n\n')[0]
        level=int(re.search(r'givemon VAR_TEMP_1, (\d+)',block).group(1))
        prizes[species]={'coins':cost,'level':level}
    return {'stations':stations,'prizes':prizes,'source_sha256':sources,'source_revision':'037335f4c725d7c9aecdac87066f2002b4bd7e14','adaptation':'Source NPC gifts, laboratory and coin clerks are mechanical stations; per-trainer claims replace global flags. Fossil revival requires actual departure and return, not elapsed time. Game Corner gambling is not simulated; original paid bundles remain available. Because all source non-gambling awards are multiples of ten and original Porygon costs9999coins, the counter also sells only the final sub-50 cap remainder at the source exchange rate20money per coin. This declared mechanical adaptation supplies no gambling win.'}
def quantity(h,item):
    inventory=h.get('inventory',{});key=next((k for k in inventory if k.upper()==item),item);value=inventory.get(key,0)
    return value.get('quantity',0) if isinstance(value,dict) else value

def near(h,station):return h['map_id']==station['map_id'] and abs(h['x']-station['x'])+abs(h['y']-station['y'])<=1

def acquisition_actions(h):
    catalog=source_catalog();stations=catalog['stations'];saved=h.get('acquisition',{});actions=[]
    def add(action,args,**known):actions.append(LegalAction(action=action,arguments=args,known_consequences={**known,'source_adaptation':catalog['adaptation']}))
    for name,item in [('old_amber','OLD_AMBER'),('coin_case','COIN_CASE')]:
        if near(h,stations[name]) and name not in saved.get('claims',[]):add('acquire_key_gift',{'gift_id':name},item=item)
    if h.get('access',{}).get('fossil_researcher_defeated') and not saved.get('fossil_choice'):
        for name in ['helix','dome']:
            if near(h,stations[name]):add('choose_fossil',{'fossil':name.upper()+'_FOSSIL'},requires_actual_miguel_win=True)
    room=len(h.get('party',[]))<6 or len(h.get('box',[]))<420
    if near(h,stations['laboratory']):
        fossil=saved.get('reviving')
        if fossil and saved.get('left_lab') and room:add('collect_revived_fossil',{},species=FOSSILS[fossil],level=5)
        elif not fossil:
            for item in FOSSILS:
                if quantity(h,item)>0:add('submit_fossil',{'fossil':item},consumes=item,requires_leave_and_return=True)
    if quantity(h,'COIN_CASE')>0:
        if near(h,stations['coins']):
            bundles=[(50,1000),(500,10000)]
            remainder=9999-saved.get('coins',0)
            if 0<remainder<50:bundles.append((remainder,remainder*20))
            for amount,cost in bundles:
                if h.get('money',0)>=cost and saved.get('coins',0)+amount<=9999:add('buy_coins',{'amount':amount},cost=cost)
        if near(h,stations['prizes']) and room:
            for species,row in catalog['prizes'].items():
                if saved.get('coins',0)>=row['coins']:add('redeem_prize',{'species':species},**row)
    return actions

def acquisition_effects(h,action,args,rng):
    if not any(a.action==action and a.arguments==args for a in acquisition_actions(h)):raise AcquisitionError('Source station unavailable: location, actual victory, claims, currency or capacity')
    h=copy.deepcopy(h);saved=h.setdefault('acquisition',{});inventory=h.setdefault('inventory',{});pokemon=None;catalog=source_catalog()
    def item_change(item,amount):
        key=next((k for k in inventory if k.upper()==item),item);q=quantity(h,item)+amount
        inventory[key]={'item_id':item,'quantity':q}
    if action=='acquire_key_gift':
        gift=args['gift_id'];item_change(gift.upper(),1);saved.setdefault('claims',[]).append(gift)
    elif action=='choose_fossil':item_change(args['fossil'],1);saved['fossil_choice']=args['fossil']
    elif action=='submit_fossil':item_change(args['fossil'],-1);saved['reviving']=args['fossil'];saved['left_lab']=False
    elif action=='buy_coins':
        amount=args['amount'];h['money']-=amount*20;saved['coins']=saved.get('coins',0)+amount
    elif action in ['collect_revived_fossil','redeem_prize']:
        if action=='collect_revived_fossil':species=FOSSILS[saved.pop('reviving')];level=5;saved.pop('left_lab',None)
        else:
            species=args['species'];row=catalog['prizes'][species];level=row['level'];saved['coins']-=row['coins']
        count=saved.get('received_count',0)+1;saved['received_count']=count
        pokemon=create_pokemon(species,level,h['human_id'],rng,identifier=f'pokemon-acquisition-{h["human_id"]}-{count}')
        pokemon['origin_map_id']=h['map_id'];pokemon['pokeball']='POKE_BALL'
        destination='party' if len(h.get('party',[]))<6 else 'box'
        h.setdefault(destination,[]).append(pokemon['pokemon_id'])
        h['pokedex']=sorted(set(h.get('pokedex',[])+[pokemon['species']]))
    return h,pokemon,{'action':action,'arguments':args,'source_sha256':catalog['source_sha256'],'adaptation':catalog['adaptation']}

def transition_acquisition(h,source_map,target_map):
    """Called only on accepted physical transfer, including canonical journey steps."""
    saved=copy.deepcopy(h.get('acquisition',{}))
    if saved.get('reviving') and source_map==LAB and target_map=='CinnabarIsland_PokemonLab_Entrance':saved['left_lab']=True
    return saved
