#!/usr/bin/env python3
"""Pin source evidence and declare deliberate shared-world station adaptations."""
import json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];REF=ROOT/'reference/pokefirered'
rows=[
 ('bill_cell_separator','Route25_SeaCottage',4,5,None,[],[],0),
 ('bill_ticket','Route25_SeaCottage',7,5,'ss_ticket',[],['bill_cell_separator'],0),
 ('captain_cut','SSAnne_CaptainsOffice',5,4,'HM01',['ss_ticket'],[],0),
 ('safari_surf','SafariZone_SecretHouse',6,5,'HM03',[],[],0),
 ('warden_strength','FuchsiaCity_WardensHouse',3,5,'HM04',['gold_teeth'],[],0),
 ('route16_fly','Route16_House',4,2,'HM02',[],[],0),
 ('aide_flash','Route2_EastBuilding',4,6,'HM05',[],[],10),
 ('hideout_scope','RocketHideout_B4F',20,5,'silph_scope',['lift_key'],[],0),
 ('tower_fuji_release','PokemonTower_7F',11,4,None,[],[],0),
 ('fuji_flute','LavenderTown_VolunteerPokemonHouse',3,3,'poke_flute',[],['tower_fuji_release'],0),
 ('fanclub_bike_voucher','VermilionCity_PokemonFanClub',5,4,'bike_voucher',[],[],0),
 ('bike_exchange','CeruleanCity_BikeShop',9,3,'bicycle',['bike_voucher'],[],0),
 ('celadon_tea','CeladonCity_Condominiums_1F',2,9,'tea',[],[],0),
]
scenarios=[]
for sid,mid,x,y,reward,required,prior,caught in rows:
 source=f'data/maps/{mid}/scripts.inc';text=(REF/source).read_text()
 if reward:assert ('ITEM_'+reward.upper()) in text
 scenarios.append({'id':sid,'map_id':mid,'x':x,'y':y,'reward':reward,'required_items':required,'required_access':['tower_marowak_defeated'] if sid in ('tower_fuji_release','fuji_flute') else [],'required_scenarios':prior,'caught_species':caught,'consumes':['gold_teeth'] if sid=='warden_strength' else ['bike_voucher'] if sid=='bike_exchange' else [],'duration_seconds':1,'source':source,'source_sha256':hashlib.sha256((REF/source).read_bytes()).hexdigest(),'adaptation':'A repeatable environmental station at the source interaction coordinate grants this trainer the source reward after its mechanical conditions. NPC speech/behavior is not scripted. Completion is per trainer; the station remains for others. Duration is one simulation action, an explicit timing adaptation.'})
(ROOT/'content/scenarios.json').write_text(json.dumps({'schema_version':1,'source_revision':'037335f4c725d7c9aecdac87066f2002b4bd7e14','adaptations':['Bill console remains functional without a global transformed-Bill plot state; operating it precedes the ticket station.','Captain first-aid station replaces scripted backrub interaction, requires own SS Ticket.','Tea kiosk, HM gift stations, and Gold Teeth exchange are mechanical repeatable stations; they do not choose actions for the persistent AI residents.','Flash requires ten distinct caught species recorded by the engine (GetPokedexCount VAR_0x8006), not merely seen species.','Silph Scope station at its source item coordinate requires own Lift Key and actual Hideout navigation. It substitutes the excluded scripted Rocket campaign and records no Giovanni or grunt battle victory.',
 'Fuji release replaces the excluded scripted Rocket campaign with an environmental summit station after a real uncatchable Marowak ghost victory; no Rocket trainer victory is invented.',
 'Safari entrance admission and every traversal/key gate remain separately enforced; reaching this station does not grant a badge.'], 'scenarios':scenarios},indent=2)+'\n')
