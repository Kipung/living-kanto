"""Source letter limits and atomic, entity-owned lifecycle; no runtime minds."""
import copy
from types import SimpleNamespace
import pytest
from living_kanto.mechanics.mail import (mail_types,mailbox_capacity,write_mail,read_mail,mail_to_pc,mail_attach,mail_discard,propose_mail,mail_actions)
from living_kanto.mechanics.item_rules import ItemError,item_catalog
from living_kanto.mechanics.inventory import quantity,limits


def fixture():
    t={'human_id':'a','name':'Alice','party':['p'],'box':[], 'inventory':{'orange_mail':2}}
    p={'pokemon_id':'p','owner_id':'a','species':'PIDGEY','held_item':''}
    return t,p


def written():
    t,p=fixture()
    return write_mail(t,p,'ORANGE_MAIL','Meet me in Pewter City.',mail_id='letter-1')[:2]


def test_source_mail_types_capacity_and_atomic_writing():
    assert len(mail_types())==12 and mailbox_capacity()==10
    t,p=fixture();p['held_item']='ORAN_BERRY';before=copy.deepcopy((t,p))
    nt,np,event=write_mail(t,p,'orange mail','Meet me in Pewter City.',mail_id='letter-1')
    assert (t,p)==before
    assert quantity(nt['inventory'],'orange_mail')==1
    assert quantity(nt['inventory'],'oran_berry')==1
    assert np['mail']=={'mail_id':'letter-1','item':'ORANGE_MAIL','text':'Meet me in Pewter City.','author_id':'a','author_name':'Alice','species':'PIDGEY'}
    assert event['text_adaptation']=='free_text_200'
    assert read_mail(nt,np)==np['mail']
    changed=read_mail(nt,np);changed['text']='overwrite'
    assert read_mail(nt,np)['text']=='Meet me in Pewter City.'


@pytest.mark.parametrize('text',['',' '*5,'x'*201,None])
def test_write_rejects_empty_and_overlong_text_without_consuming_item(text):
    t,p=fixture();before=copy.deepcopy((t,p))
    with pytest.raises(ItemError):write_mail(t,p,'ORANGE_MAIL',text,mail_id='letter-1')
    assert (t,p)==before


@pytest.mark.parametrize('invalid',['foreign','stored','egg'])
def test_mail_cannot_be_written_read_or_attached_to_foreign_stored_or_egg_individual(invalid):
    t,p=written();t['mailbox']={'letter-2':{**p['mail'],'mail_id':'letter-2'}}
    if invalid=='foreign':p['owner_id']='b'
    if invalid=='stored':t['party']=[];t['box']=['p']
    if invalid=='egg':p['is_egg']=True
    with pytest.raises(ItemError):read_mail(t,p)
    with pytest.raises(ItemError):mail_to_pc(t,p)
    with pytest.raises(ItemError):mail_attach(t,p,'letter-2')
    p.pop('mail')
    with pytest.raises(ItemError):write_mail(t,p,'ORANGE_MAIL','Hi',mail_id='letter-new')


def test_mailbox_roundtrip_consumes_letter_entry_and_preserves_author_species_and_text():
    t,p=written();letter=copy.deepcopy(p['mail']);before=copy.deepcopy((t,p))
    nt,np,_=mail_to_pc(t,p)
    assert (t,p)==before and not np.get('mail') and not np['held_item']
    assert nt['mailbox']=={'letter-1':letter}
    np['species']='PIDGEOT';np['held_item']='POTION'
    final,p2,_=mail_attach(nt,np,'letter-1')
    assert final['mailbox']=={} and p2['mail']==letter and p2['held_item']=='ORANGE_MAIL'
    assert quantity(final['inventory'],'POTION')==1
    with pytest.raises(ItemError):mail_attach(final,{**p2,'held_item':'','mail':None},'letter-1')
    assert final['mailbox']=={}


def test_mailbox_capacity_is_ten_and_full_failure_is_atomic():
    t,p=written();t['mailbox']={f'old-{i}':{**p['mail'],'mail_id':f'old-{i}'} for i in range(10)}
    before=copy.deepcopy((t,p))
    with pytest.raises(ItemError,match='full'):mail_to_pc(t,p)
    assert (t,p)==before
    t['mailbox'].pop('old-9');nt,np,_=mail_to_pc(t,p)
    assert len(nt['mailbox'])==10 and not np.get('mail')


def test_discard_requires_explicit_text_deletion_and_returns_one_blank_mail():
    t,p=written();before=copy.deepcopy((t,p))
    with pytest.raises(ItemError,match='explicit'):mail_discard(t,pokemon=p)
    assert (t,p)==before
    nt,np,event=mail_discard(t,pokemon=p,discard_mail=True)
    assert quantity(nt['inventory'],'orange_mail')==2 and not np.get('mail')
    assert event['text_deleted'] is True
    with pytest.raises(ItemError):mail_discard(nt,pokemon=np,discard_mail=True)
    t,p=written();nt,np,_=mail_to_pc(t,p)
    final,unused,_=mail_discard(nt,mail_id='letter-1',discard_mail=True)
    assert unused is None and final['mailbox']=={} and quantity(final['inventory'],'orange_mail')==2


def test_full_bag_blocks_returns_without_erasing_letter_or_consuming_mail():
    t,p=written();t['inventory']={'orange_mail':999};before=copy.deepcopy((t,p))
    with pytest.raises(ItemError,match='full'):mail_discard(t,pokemon=p,discard_mail=True)
    assert (t,p)==before
    t,p=fixture();p['held_item']='ORAN_BERRY'
    berries=[key.lower() for key,row in item_catalog().items() if row['pocket']=='POCKET_BERRY_POUCH' and key!='ORAN_BERRY']
    t['inventory'].update({key:1 for key in berries[:limits()['POCKET_BERRY_POUCH']]})
    # The cartridge has 43 berries and 43 berry slots: fill stack instead.
    t['inventory']['oran_berry']=999;before=copy.deepcopy((t,p))
    with pytest.raises(ItemError,match='full'):write_mail(t,p,'ORANGE_MAIL','Hi',mail_id='letter-1')
    assert (t,p)==before


def test_author_retained_when_same_pokemon_changes_owner_and_mail_moves_to_new_mailbox():
    t,p=written();letter=copy.deepcopy(p['mail'])
    recipient={'human_id':'b','name':'Bob','party':['p'],'box':[],'inventory':{}}
    transferred=copy.deepcopy(p);transferred['owner_id']='b'
    assert read_mail(recipient,transferred)==letter
    nt,np,_=mail_to_pc(recipient,transferred)
    assert nt['mailbox']['letter-1']['author_id']=='a'
    assert nt['mailbox']['letter-1']['author_name']=='Alice'
    with pytest.raises(ItemError):read_mail(t,transferred)
    assert p['mail']==letter


def test_dispatcher_rejects_duplicate_identifiers_and_invalid_arguments():
    t,p=written();empty={**p,'pokemon_id':'q','mail':None,'held_item':''};t['party'].append('q')
    with pytest.raises(ItemError,match='already attached'):propose_mail(t,{'p':p,'q':empty},'write_mail',{'pokemon_id':'q','item':'ORANGE_MAIL','text':'Hi'},new_mail_id='letter-1')
    with pytest.raises(ItemError):propose_mail(t,{'p':p},'mail_to_pc',{'pokemon_id':'p','unexpected':True})
    with pytest.raises(ItemError):propose_mail(t,{'p':p},'mail_discard',{'pokemon_id':'p','discard_mail':False})
    nt,updates,event=propose_mail(t,{'p':p},'read_mail',{'pokemon_id':'p'})
    assert updates=={} and nt==t and event['contents']==p['mail']


def test_gameplay_options_are_private_party_only_and_pc_actions_require_pc_context():
    t,p=written();other={**p,'pokemon_id':'foreign','owner_id':'b'}
    state=SimpleNamespace(humans={'a':t},pokemon={'p':p,'foreign':other})
    actions=mail_actions(state,'a');names={a.action for a in actions}
    assert names=={'read_mail','mail_discard'} and all(a.arguments.get('pokemon_id')=='p' for a in actions)
    assert 'mail_to_pc' in {a.action for a in mail_actions(state,'a',at_pc=True)}
    t['battle_id']='battle';assert mail_actions(state,'a',at_pc=True)==[]


def test_new_letter_cannot_replace_existing_letter_and_boundary_text_is_accepted():
    t,p=written();before=copy.deepcopy((t,p))
    with pytest.raises(ItemError,match='existing mail'):write_mail(t,p,'ORANGE_MAIL','Overwrite',mail_id='letter-2')
    assert (t,p)==before
    t,p=fixture();nt,np,_=write_mail(t,p,'ORANGE_MAIL','x'*200,mail_id='letter-boundary')
    assert len(np['mail']['text'])==200
    with pytest.raises(ItemError):write_mail(t,p,'POTION','Hi',mail_id='wrong-item')


def test_dispatcher_cannot_attach_duplicated_letter_from_mailbox():
    t,p=written();t['mailbox']={'letter-1':copy.deepcopy(p['mail'])};t['party'].append('q')
    q={**p,'pokemon_id':'q','held_item':'','mail':None};before=copy.deepcopy((t,p,q))
    with pytest.raises(ItemError,match='already attached'):propose_mail(t,{'p':p,'q':q},'mail_attach',{'pokemon_id':'q','mail_id':'letter-1'})
    assert (t,p,q)==before
