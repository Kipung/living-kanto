"""Pinned shop inventories and prices from actual pokemart script tables."""
import re
from functools import lru_cache
from .reference import REFERENCE
from .item_rules import item_catalog

@lru_cache(maxsize=1)
def shop_catalog():
    result={};catalog=item_catalog()
    for path in sorted((REFERENCE/'data/maps').glob('*/scripts.inc')):
        text=path.read_text();items={}
        for label in re.findall(r'^\s*pokemart\s+(\w+)',text,re.M):
            table=re.search(r'^'+label+r'::\n(.*?\.2byte ITEM_NONE)',text,re.S|re.M)
            if not table:raise ValueError(f'Source shop table missing {label}')
            for item in re.findall(r'\.2byte ITEM_(\w+)',table.group(1)):
                if item=='NONE':continue
                key=item.split('_',1)[0] if re.match(r'TM\d\d_',item) else item
                items[key.lower()]=catalog[key]['price']
        if items:result[path.parent.name]=items
    return result
