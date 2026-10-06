"""Audit every imported map edge using compiled pinned-source predicates.

This is a terrain audit, not an emulator or a claim of full engine equivalence.
Door, ledge, Surf and warp exceptions are separately classified/tested.
"""
import ctypes,hashlib,json,re,subprocess,tempfile
from pathlib import Path
from living_kanto.simulation.maps import GameMap
ROOT=Path(__file__).resolve().parents[1]
def function(text,name):
 match=re.search(r'(?:static )?(?:bool8|u8) '+name+r'\([^;]*?\)\s*\{',text)
 if not match:raise ValueError(name)
 start=match.start();i=match.end();depth=1
 while depth:
  depth+=(text[i]=='{')-(text[i]=='}');i+=1
 return text[start:i]
def audit():
 source=ROOT/'reference/pokefirered';obj=(source/'src/event_object_movement.c').read_text();mb=(source/'src/metatile_behavior.c').read_text()
 names=['East','West','North','South'];code='typedef unsigned char u8; typedef unsigned char bool8; typedef short s16;\n#define TRUE 1\n#define FALSE 0\n'
 code+=(source/'include/constants/metatile_behaviors.h').read_text()+'\nstatic u8 level; u8 MapGridGetElevationAt(s16 x,s16 y){return level;}\n'
 for direction in names:code+=function(mb,'MetatileBehavior_Is'+direction+'Blocked')+'\n'
 code+=function(obj,'IsElevationMismatchAt')+'\n'+function(obj,'AreElevationsCompatible')+'\n'
 code+='int mismatch(int a,int b){level=b;return IsElevationMismatchAt(a,0,0);}\nint compatible(int a,int b){return AreElevationsCompatible(a,b);}\n'
 report={'source_revision':'037335f4c725d7c9aecdac87066f2002b4bd7e14','source_sha256':hashlib.sha256((obj+mb).encode()).hexdigest(),'maps':0,'edges_checked':0,'blocked_warp_markers':0,'exceptions':{},'violations':[]}
 water={0x10,0x11,0x12,0x13,0x15,0x1A,0x1B,0x50,0x51,0x52,0x53};opposite={'east':'West','west':'East','north':'South','south':'North'}
 with tempfile.TemporaryDirectory() as tmp:
  c=Path(tmp)/'native.c';so=Path(tmp)/'native.dylib';c.write_text(code);subprocess.run(['cc','-shared','-fPIC','-O2',str(c),'-o',str(so)],check=True,capture_output=True);lib=ctypes.CDLL(str(so))
  for path in sorted((ROOT/'content/maps').glob('*.json')):
   m=GameMap.from_content(path.stem,path);report['maps']+=1
   for w in m.events.get('warp_events',[]):
    if m.cells.get((w['x'],w['y']),{}).get('collision'):report['blocked_warp_markers']+=1
   for p,old in m.cells.items():
    if not m.is_walkable(*p):continue
    for d,(dx,dy) in {'north':(0,-1),'south':(0,1),'east':(1,0),'west':(-1,0)}.items():
     n=(p[0]+dx,p[1]+dy);target=m.cells.get(n,{})
     # The source player's exceptions are not ordinary object movement.
     classification=next((name for name,condition in [('door',old.get('behavior')==0x69 or target.get('behavior')==0x69),('ledge',target.get('behavior') in {0x38,0x39,0x3A,0x3B}),('water',target.get('behavior') in water),('retained_elevation',old.get('elevation')==15)] if condition),None)
     if classification:report['exceptions'][classification]=report['exceptions'].get(classification,0)+1;continue
     blocked=(not m.in_bounds(*n) or target.get('collision',0) or getattr(lib,'MetatileBehavior_Is'+d.title()+'Blocked')(old.get('behavior',0)) or getattr(lib,'MetatileBehavior_Is'+opposite[d]+'Blocked')(target.get('behavior',0)) or lib.mismatch(old.get('elevation',0),target.get('elevation',0)))
     actual=m._step_basic(p,d) is None;report['edges_checked']+=1
     if bool(blocked)!=actual:report['violations'].append({'map':m.map_id,'from':p,'direction':d,'native_blocked':bool(blocked),'sim_blocked':actual})
  from living_kanto.simulation.collision import compatible_elevations
  for a in range(16):
   for b in range(16):assert bool(lib.compatible(a,b))==compatible_elevations(a,b)
 return report
if __name__=='__main__':
 report=audit();out=ROOT/'evidence/physics/source-collision-audit.json';out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k!='violations'},indent=2));print('Violations:',len(report['violations']));raise SystemExit(bool(report['violations']))
