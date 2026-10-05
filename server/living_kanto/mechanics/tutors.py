"""Source tutor NPC coordinates, dialogue move and species compatibility.

Stations model these scripted source services without creating extra human minds;
source global one-use flags are deliberately scoped to each persistent trainer.
"""
import json,re
from functools import lru_cache
from .reference import REFERENCE

@lru_cache(maxsize=1)
def tutor_stations():
    scripts=(REFERENCE/'data/scripts/move_tutors.inc').read_text()
    blocks=dict(re.findall(r'^(\w+)::\n(.*?)(?=^\w+::|\Z)',scripts,re.S|re.M))
    for script in sorted((REFERENCE/'data/maps').glob('*/scripts.inc')):
        blocks.update(re.findall(r'^(\w+)::\n(.*?)(?=^\w+::|\Z)',script.read_text(),re.S|re.M))
    result=[]
    for path in sorted((REFERENCE/'data/maps').glob('*/map.json')):
        row=json.loads(path.read_text())
        for index,npc in enumerate(row.get('object_events',[])):
            body=blocks.get(npc.get('script',''),'')
            for target in re.findall(r'(?:goto|call)(?:_if_\w+)?[^\n]*?(EventScript_\w+Tutor)',body):body+='\n'+blocks.get(target,'')
            move=re.search(r'setvar VAR_0x8005, MOVETUTOR_(\w+)',body)
            if move:result.append({'tutor_id':f'tutor-{row["name"].lower()}-{index}','map_id':row['name'],'x':npc['x'],'y':npc['y'],'move':move.group(1),'source_script':npc['script']})
    return tuple(result)
