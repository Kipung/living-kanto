import json
import subprocess
from pathlib import Path
from living_kanto.mechanics import BattleSession
from living_kanto.mechanics.battle import HERE


def test_hundred_turn_six_versus_six_state_compressed_and_restorable():
    # Actual Gen III simulator executes 100 simultaneous switching turns. No
    # models or fake state are involved; switching avoids ending the stress run.
    script="""
const {Battle}=require('pokemon-showdown');
let team=Array.from({length:6},(_,i)=>({name:'persistent-pokemon-'+i,species:'Magikarp',level:100,moves:['Splash']}));
let b=new Battle({formatid:'gen3customgame',seed:[1,2,3,4],p1:{name:'a',team},p2:{name:'b',team}});
for(let i=0;i<100;i++) {let slot=2;b.choose('p1','switch '+slot);b.choose('p2','switch '+slot);}
if(b.turn!==101 || b.ended) throw Error('Stress turn resolution failed');
b.log=b.log.filter(x=>!x.startsWith('|t:|'));
console.log(JSON.stringify({state:b.toJSON(),log:b.log,observations:{a:{log:b.log},b:{log:b.log}},turn:b.turn,ended:b.ended,winner:null}));
"""
    proc=subprocess.run(['node','-e',script],cwd=HERE,text=True,capture_output=True,check=True,timeout=20)
    result=json.loads(proc.stdout)
    session=BattleSession({'schema_version':1,'result':result,'pending':{},'history':[],'version':100})
    exported=session.to_dict()
    assert exported['result']['state']['encoding']=='zlib-base64-json'
    assert len(json.dumps(exported).encode())<120000
    restored=BattleSession(json.loads(json.dumps(exported)))
    assert restored.record['result']['state']==session.record['result']['state']
    assert len(restored.record['result']['log'])<=200
    assert all(len(o['log'])<=200 for o in restored.record['result']['observations'].values())
    assert restored.record['result']['state']['turn']==101
