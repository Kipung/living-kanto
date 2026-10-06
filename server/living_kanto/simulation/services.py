"""Human-operated FIFO service queues; no automatic staff mind.

Adaptation: a purchase reserves payment when requested, then a local staff
human chooses to serve the head. Healing/purchases consume sequential shared
simulated time. Requests and receipts are canonical persisted state changes. Every queued human
may explicitly cancel. A station's sole assigned staff cannot request their own
service: shared-world staffing adaptation, not cartridge NPC behavior.
"""
import copy
from ..contracts.human import LegalAction
from .engine import EngineError
from ..mechanics import heal

from ..mechanics.shops import shop_catalog


class ServiceMixin:
    @staticmethod
    def service_kind(map_id):
        if 'PokemonCenter_1F' in map_id:return 'healing'
        if map_id in shop_catalog():return 'shop'
        return None

    @staticmethod
    def shop_prices(map_id):return dict(shop_catalog().get(map_id,{}))

    def setup_services(self,humans):
        healing=sorted(mid for mid in self.maps if 'PokemonCenter_1F' in mid)
        shops=sorted(mid for mid in self.maps if self.shop_prices(mid))
        nurses=[h for h in humans.values() if h.get('role')=='service_staff']
        clerks=[h for h in humans.values() if h.get('role')=='shop_staff']
        assignments=[]
        for index,human in enumerate(clerks):
            if shops:assignments.append((human,'shop',shops[index%len(shops)]))
        covered={mid for _,kind,mid in assignments if kind=='shop'}
        remaining=[('healing',mid) for mid in healing]+[('shop',mid) for mid in shops if mid not in covered]
        for index,human in enumerate(nurses):
            kind,mid=remaining[index] if index<len(remaining) else ('healing',healing[(index-len(remaining))%len(healing)])
            assignments.append((human,kind,mid))
        for index,(human,kind,mid) in enumerate(assignments):
            x,y=self.maps[mid].first_open_cell((5+index%3,5))
            human.update({'map_id':mid,'x':x,'y':y,'service_assignment':{'kind':kind,'map_id':mid}})
            human['responsibilities']=list(human.get('responsibilities',[]))+[{'kind':'staff_service','map_id':mid,'service':kind,'source':'declared_setup'}]

    def service_queue(self,state,map_id):
        return state.world_facts.get('service_queues',{}).get(map_id,[])

    def sole_assigned_staff(self,state,hid,map_id,kind):
        assignment={'kind':kind,'map_id':map_id}
        staff=[actor for actor,human in state.humans.items()
               if human.get('role') in ('service_staff','shop_staff') and human.get('service_assignment')==assignment]
        return staff==[hid]

    def service_actions(self,state,hid):
        human=state.humans[hid]
        if human.get('battle_id') or human.get('service_request'):return []
        from .workplaces import at_service_post
        if not at_service_post(human): return []
        queue=self.service_queue(state,human['map_id'])
        kind=queue[0]['kind'] if queue else self.service_kind(human['map_id'])
        assignment=human.get('service_assignment',{})
        eligible=human.get('role')=='service_staff' and kind=='healing' or human.get('role')=='shop_staff' and kind=='shop' or human.get('role') in ('service_staff','shop_staff') and assignment.get('kind')==kind and assignment.get('map_id')==human['map_id']
        if eligible and queue:
            return [LegalAction(action='serve_customer',arguments={'request_id':queue[0]['request_id']},
                known_consequences={'customer':queue[0]['human_id'],'service':kind,
                                    'duration_seconds':60 if kind=='healing' else 30})]
        return []

    def service_private_info(self,state,hid):
        h=state.humans[hid];info={}
        if h.get('service_request'):info['pending_service']=copy.deepcopy(h['service_request'])
        if self.service_actions(state,hid):info['next_customer']=copy.deepcopy(self.service_queue(state,h['map_id'])[0])
        return info

    def service_changes(self,state,hid,action,args):
        h=state.humans[hid];mid=h['map_id'];kind=self.service_kind(mid)
        queue=copy.deepcopy(self.service_queue(state,mid));changes=[]
        def setv(path,value):changes.append({'op':'set','path':path,'value':value})
        if action=='wait_for_service':
            request=h.get('service_request')
            if args or not request or request['map_id']!=mid or not any(row['request_id']==request['request_id'] for row in queue):
                raise EngineError('Waiting requires an active local service request')
            return [],'time.advanced',30
        if action=='cancel_service':
            request=h.get('service_request')
            if args or not request:raise EngineError('no queued service to cancel')
            original=request['map_id'];pending=copy.deepcopy(self.service_queue(state,original))
            if not any(row['request_id']==request['request_id'] for row in pending):raise EngineError('request missing from queue')
            setv(f'world_facts.service_queues.{original}',[row for row in pending if row['request_id']!=request['request_id']])
            setv(f'humans.{hid}.money',h['money']+request['reserved_payment'])
            setv(f'humans.{hid}.service_request',None);setv(f'humans.{hid}.status.activity','ready')
            setv(f'world_facts.service_receipts.{request["request_id"]}',{**request,'cancelled_at':state.simulated_time+1,'outcome':'cancelled','refund':request['reserved_payment']})
            return changes,'world.public_event',1
        if action in {'heal_party','shop_buy'}:
            wanted='healing' if action=='heal_party' else 'shop'
            if not (self.shop_prices(mid) if wanted=='shop' else 'PokemonCenter_1F' in mid) or h.get('battle_id') or h.get('service_request'):raise EngineError('service unavailable or customer busy')
            if self.sole_assigned_staff(state,hid,mid,wanted):raise EngineError('sole assigned staff cannot queue their own service')
            kind=wanted
            if action=='heal_party' and args:raise EngineError('healing takes no arguments')
            cost=0
            if action=='shop_buy':
                if set(args)!={'item','quantity'} or args['item'] not in self.shop_prices(mid) or type(args['quantity'])is not int or args['quantity']!=1:raise EngineError('invalid queued purchase')
                cost=self.shop_prices(mid)[args['item']]
                if h['money']<cost:raise EngineError('insufficient funds')
                from ..mechanics.inventory import add
                try: add(h['inventory'],args['item'],args['quantity'])
                except ValueError as exc: raise EngineError(str(exc)) from exc
                setv(f'humans.{hid}.money',h['money']-cost)
            request={'request_id':f'service-{state.state_version}-{hid}','human_id':hid,'map_id':mid,'kind':kind,
                     'arguments':dict(args),'reserved_payment':cost,'requested_at':state.simulated_time}
            queue.append(request);setv(f'world_facts.service_queues.{mid}',queue)
            setv(f'humans.{hid}.service_request',request);setv(f'humans.{hid}.status.activity','queued_service')
            return changes,'world.public_event',1
        if action!='serve_customer' or not any(a.arguments==args for a in self.service_actions(state,hid)):raise EngineError('only eligible local staff may serve the queue head')
        request=queue[0];kind=request['kind'];customer=state.humans[request['human_id']]
        if customer.get('map_id')!=mid or customer.get('battle_id') or customer.get('service_request',{}).get('request_id')!=request['request_id']:
            raise EngineError('queued customer moved or is unavailable; restore/cancel the interrupted request')
        if kind=='healing':
            for pid in customer['party']:
                mon=copy.deepcopy(state.pokemon[pid]);heal(mon)
                for key,value in mon.items():setv(f'pokemon.{pid}.{key}',value)
        else:
            from ..mechanics.inventory import add
            item=request['arguments']['item']
            try: inventory=add(customer['inventory'],item,request['arguments']['quantity'])
            except ValueError as exc: raise EngineError(str(exc)) from exc
            setv(f'humans.{customer["human_id"]}.inventory',inventory)
        duration=60 if kind=='healing' else 30
        receipt={**request,'staff_id':hid,'completed_at':state.simulated_time+duration,'duration_seconds':duration}
        setv(f'world_facts.service_queues.{mid}',queue[1:]);setv(f'world_facts.service_receipts.{request["request_id"]}',receipt)
        setv(f'humans.{customer["human_id"]}.service_request',None);setv(f'humans.{customer["human_id"]}.status.activity','service_completed')
        if kind=='healing':
            # Adaptation: a checkpoint is accepted only when physical healing
            # completes, rather than source single-player map-load scripting.
            setv(f'humans.{customer["human_id"]}.last_heal_station',{'map_id':mid,'request_id':request['request_id'],'completed_at':receipt['completed_at'],'source':'pret/pokefirered/src/heal_location.c'})
        setv(f'humans.{customer["human_id"]}.last_service',receipt);setv(f'humans.{hid}.last_service',receipt)
        return changes,'human.healed' if kind=='healing' else 'human.shopped',duration
