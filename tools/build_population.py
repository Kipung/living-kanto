#!/usr/bin/env python3
"""Explicit declared setup biographies; these are not simulated achievements."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TOWNS=['PalletTown','ViridianCity','PewterCity','CeruleanCity','VermilionCity','LavenderTown','CeladonCity','FuchsiaCity','SaffronCity','CinnabarIsland']
NAMES=['Ari','Bea','Cleo','Dax','Emi','Finn','Gia','Hugo','Iris','Jules','Kai','Lena','Milo','Nia','Oren','Pia','Quinn','Rhea','Soren','Tess','Uma','Vera','Wren','Xavi','Yara','Zane','Ada','Bram','Cora','Dev']
INTERESTS=['field sketching','bug ecology','fishing','music','hiking','cooking','history','photography','gardening','mechanical repair']
AMBITIONS=['complete a regional field journal','build a trusted circle of friends','earn enough to support family','study unusual habitats','improve patient handling','explore Kanto at a measured pace','challenge the gyms through careful preparation','collect and compare local species','master a balanced battle style','become a reliable mentor']
roles=[('aspiring_trainer',30),('gym_leader',8),('elite_four',4),('initial_champion',1),('professor',1),('service_staff',20),('shop_staff',10),('worker',10),('resident',16)]
leaders=['Brock','Misty','Lt. Surge','Erika','Koga','Sabrina','Blaine','Giovanni']; gyms=['PewterCity_Gym','CeruleanCity_Gym','VermilionCity_Gym','CeladonCity_Gym','FuchsiaCity_Gym','SaffronCity_Gym','CinnabarIsland_Gym','ViridianCity_Gym']
humans=[]
for role,count in roles:
 for j in range(count):
  n=len(humans); town=TOWNS[(n*7+j)%10]; name=NAMES[j] if role=='aspiring_trainer' else f'{NAMES[n%30]} {("Vale","Reed","Stone","Moss")[n%4]}'
  if role=='gym_leader':name=leaders[j];town=gyms[j]
  if role=='elite_four':name=['Lorelei','Bruno','Agatha','Lance'][j];town=['PokemonLeague_LoreleisRoom','PokemonLeague_BrunosRoom','PokemonLeague_AgathasRoom','PokemonLeague_LancesRoom'][j]
  if role=='initial_champion':name='Blue';town='PokemonLeague_ChampionsRoom'
  if role=='professor':name='Professor Oak';town='PalletTown_ProfessorOaksLab'
  interest=INTERESTS[n%10]; ambition=AMBITIONS[(n*3+j)%10]
  humans.append({'human_id':f'human-{n+1:03d}','name':name,'role':role,'map_id':town,'appearance':{'sprite':'prof_oak' if role=='professor' else 'nurse' if role=='service_staff' else 'red_normal' if n%2 else 'green_normal','palette':n%4},'biography':f'{name} grew up near {TOWNS[(n+3)%10]} and now lives in {town.split("_")[0]}. Their early experience with {interest} shapes how they notice the world. They want to {ambition}.','personality':{'curiosity':round(.2+(n%9)*.08,2),'sociability':round(.15+(n*5%10)*.08,2),'patience':round(.2+(n*3%9)*.08,2),'risk_tolerance':round(.1+(n*7%10)*.085,3)},'interests':[interest,INTERESTS[(n+4)%10]],'ambitions':[ambition],'preferences':{'activity_time':'morning' if n%3==0 else 'evening' if n%3==1 else 'afternoon','favorite_type':['grass','water','fire','electric','bug','rock','psychic','normal','flying','poison'][n%10]},'money':1500+125*(n%13),'inventory':{'POTION':1+n%3,'POKE_BALL':5} if role=='aspiring_trainer' else {},'responsibilities':[] if role=='aspiring_trainer' else [{'role':role,'workplace':town,'shift':'day' if n%2 else 'late'}],'goals':[{'id':f'initial-{n+1}','text':ambition,'source':'declared_setup'}],'active_plan':None,'party':[],'box':[],'badges':[],'pokedex':[],'memories':[{'id':f'background-{n+1}','text':f'I remember learning {interest} near {TOWNS[(n+3)%10]}.','source':'declared_setup','subjective':True}],'memory_summary':'','relationships':{f'human-{(n+17)%100+1:03d}':{'familiarity':.2,'trust':round(.1+(n%5)*.1,1),'belief':'An acquaintance from earlier travels; I should learn more.'}},'needs':{'energy':70+n%31,'rest':n%15,'social':20+n%50},'decision_history':[],'model_provenance':[],'setup_status':role if role in ['gym_leader','elite_four','initial_champion','professor'] else None})
(ROOT/'content/population.json').write_text(json.dumps({'schema_version':1,'setup_note':'Biographies and incumbent titles are declared initial conditions, not achievements. Aspiring trainers have zero badges.','humans':humans},indent=2)+'\n')
print(len(humans),'declared individuals')
