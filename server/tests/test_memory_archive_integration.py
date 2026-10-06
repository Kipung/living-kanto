import copy
from test_gameplay import game,state,scenario,act

def test_bounded_recall_keeps_archive_and_new_memory_appends_after_full_history(game):
 e,store=game;hid='human-001'
 memories={str(n):{'text':f'I saw stone number {n}','time':n} for n in range(40)}
 scenario(game,[{'op':'set','path':f'humans.{hid}.memories','value':memories}])
 before=state(game);original=copy.deepcopy(before.humans[hid]['memories'])
 obs=e.observation_for(before,hid).to_dict()
 assert len(obs['memories'])<=16
 assert obs['self_state']['memory_recall']['stored_memories']==40
 assert before.humans[hid]['memories']==original
 assert state(game).state_hash==before.state_hash
 after=act(game,hid,'remember',{'text':'I promised to meet Pia'})
 assert len(after.humans[hid]['memories'])==41
 assert after.humans[hid]['memories']['40']['text']=='I promised to meet Pia'
 assert all(after.humans[hid]['memories'][key]==value for key,value in original.items())
 assert store.replay('gameplay-test').state_hash==after.state_hash
