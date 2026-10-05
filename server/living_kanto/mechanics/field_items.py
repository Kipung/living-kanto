"""Source Repel durations and reusable encounter flute effects."""
import copy
from .item_rules import item_catalog,ItemError,_consume

def apply_field_item(trainer,item):
    key=item.upper()
    if key not in ('REPEL','SUPER_REPEL','MAX_REPEL','BLACK_FLUTE','WHITE_FLUTE'):raise ItemError('Field item effect unsupported')
    if trainer.get('battle_id') or trainer.get('safari',{}).get('encounter'):raise ItemError('Field item cannot be used during battle')
    h=copy.deepcopy(trainer);counter=h.setdefault('field_encounter',{})
    if key.endswith('REPEL'):
        if counter.get('repel_steps',0):raise ItemError('Previous Repel still active')
        _consume(h,key,amount=1);counter['repel_steps']=item_catalog()[key]['holdEffectParam']
    else:
        _consume(h,key,amount=0);counter['flute']='black' if key=='BLACK_FLUTE' else 'white'
    return h,{'item':key,'field_encounter':copy.deepcopy(counter),'source':'src/item_use.c FieldUseFunc_Repel/BlackWhiteFlute'}
