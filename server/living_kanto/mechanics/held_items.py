"""Source give/take eligibility and atomic inventory/individual changes."""
import copy
from .item_rules import item_catalog,_item,_owner,_consume,ItemError
from .reference import data

def holdable(item):
    key=_item(item);row=item_catalog()[key]
    return key!='NONE' and row['pocket']!='POCKET_KEY_ITEMS' and row.get('importance',0)==0 and row.get('type')!='ITEM_TYPE_MAIL'

def change_held_item(trainer,pokemon,item=None):
    _owner(trainer,pokemon)
    if trainer.get('battle_id'):raise ItemError('Cannot change held item during battle')
    if pokemon.get('is_egg') or pokemon.get('mail') or item_catalog().get(pokemon.get('held_item'),{}).get('type')=='ITEM_TYPE_MAIL':raise ItemError('Mail or egg requires its source-specific menu')
    h=copy.deepcopy(trainer);p=copy.deepcopy(pokemon);old=p.get('held_item') or ''
    if item is None:
        if not old:raise ItemError('No held item to take')
        p['held_item']=''
    else:
        key=_item(item)
        if not holdable(key):raise ItemError('Source item cannot be held or mail writing unsupported')
        if key==old:raise ItemError('Already holding that item')
        _consume(h,key);p['held_item']=key
    if old:
        row=h['inventory'].setdefault(old.lower(),{'quantity':0});row['quantity']+=1
    return h,p

def assign_wild_held_item(pokemon,rng):
    """SetWildMonHeldItem: no Compound Eyes bonus in pinned FireRed source."""
    row=data()['species'][pokemon['species']];common=row['itemCommon'];rare=row['itemRare'];draw=rng.randrange(100)
    chosen=common if common==rare else rare if draw>94 else common if draw>44 else 'NONE'
    pokemon['held_item']='' if chosen=='NONE' else chosen
    return pokemon['held_item']
