"""Source scripted legendary positions and levels; mainland source scope."""
import json,re
from functools import lru_cache
from .reference import REFERENCE

@lru_cache(maxsize=1)
def static_templates():
    result={}
    for map_id,species in [('PowerPlant','ZAPDOS'),('CeruleanCave_B1F','MEWTWO'),('SeafoamIslands_B4F','ARTICUNO')]:
        scripts=(REFERENCE/'data/maps'/map_id/'scripts.inc').read_text()
        objects=json.loads((REFERENCE/'data/maps'/map_id/'map.json').read_text())['object_events']
        for obj in objects:
            block=re.search(r'^'+re.escape(obj['script'])+r'::\n(.*?)(?=^\w+::|\Z)',scripts,re.M|re.S)
            if not block:continue
            match=re.search(r'setwildbattle SPECIES_'+species+r',\s*(\d+)',block.group(1))
            if match:result[species.lower()]={'static_id':species.lower(),'map_id':map_id,'species':species,'level':int(match.group(1)),'x':obj['x'],'y':obj['y'],'script':obj['script']}
    return result

@lru_cache(maxsize=1)
def electrode_templates():
    mid='PowerPlant';scripts=(REFERENCE/'data/maps'/mid/'scripts.inc').read_text();result={}
    for obj in json.loads((REFERENCE/'data/maps'/mid/'map.json').read_text())['object_events']:
        block=re.search(r'^'+re.escape(obj['script'])+r'::\n(.*?)(?=^\w+::|\Z)',scripts,re.M|re.S)
        if not block:continue
        match=re.search(r'setwildbattle SPECIES_ELECTRODE,\s*(\d+)',block.group(1))
        if match:result[obj['script'].rsplit('_',1)[-1].lower()]={'map_id':mid,'species':'ELECTRODE','level':int(match.group(1)),'x':obj['x'],'y':obj['y'],'script':obj['script']}
    return result
