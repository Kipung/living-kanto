"""Local HTTP numbered transport; no runtime-human scripted fallback."""
import copy
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest
from living_kanto.runtime.providers import LocalModelConfig, LocalModelProvider, ProviderError
from living_kanto.runtime.decision_wire import build_decision_wire
from living_kanto.runtime.controller import RuntimeController


def observation():
    return {'human_id':'alice','memories':[{'text':'Private ambition'}], 'state_version':2,
            'legal_actions':[{'action':'wait','arguments':{'seconds':30},'known_consequences':{}},
                             {'action':'remember','arguments':{'text':'<non-empty text, <=200 chars>'},'known_consequences':{}}]}


@pytest.mark.parametrize('protocol,path', [('openai','/v1/chat/completions'),('ollama','/api/chat')])
def test_numbered_http_decodes_exact_arguments_and_preserves_private_facts(protocol,path):
    captured=[]
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            captured.append((self.path,json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
            text=json.dumps({'option':2,'text':'I hope to travel','decision_explanation':'Remember my intention'})
            result={'choices':[{'message':{'content':text}}]} if protocol=='openai' else {'message':{'content':text}}
            self.send_response(200);self.end_headers();self.wfile.write(json.dumps(result).encode())
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        provider=LocalModelProvider(LocalModelConfig(f'http://127.0.0.1:{server.server_port}','local-test',protocol,response_protocol='numbered'))
        obs=observation();before=copy.deepcopy(obs)
        assert json.loads(provider.complete(obs,correction='Invalid text'))=={'action':'remember','arguments':{'text':'I hope to travel'},'decision_explanation':'Remember my intention'}
        assert obs==before
        assert captured[0][0]==path
        payload=captured[0][1]
        facts=json.loads(payload['messages'][1]['content'])['facts']
        assert facts['memories']==obs['memories']
        assert 'numbered choice' in payload['messages'][-1]['content']
        schema=payload['response_format']['json_schema']['schema'] if protocol=='openai' else payload['format']
        assert schema['properties']['option']['enum']==[1,2]
        assert 'anyOf' not in schema
    finally:server.shutdown();server.server_close();thread.join(2)


def test_invalid_numbered_or_canonical_response_cannot_escape_decoder():
    provider=LocalModelProvider(LocalModelConfig('http://127.0.0.1:1','local-test',response_protocol='numbered'))
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,*args):return json.dumps({'choices':[{'message':{'content':json.dumps({'action':'wait','arguments':{'seconds':30},'decision_explanation':'Bypass decoder'})}}]}).encode()
    class Opener:
        def open(self,*args,**kwargs):return Response()
    provider._opener=Opener()
    result=json.loads(provider.complete(observation()))
    assert set(result)=={'numbered_response_error'}


def test_double_menu_enumerates_both_slots_and_excludes_duplicate_switch():
    obs=observation()
    first=[{'type':'move','slot':1,'target':1},{'type':'switch','slot':3}]
    second=[{'type':'move','slot':2,'target':2},{'type':'switch','slot':3}]
    obs['legal_actions']=[{'action':'battle_turn','arguments':{'choices':[first[0],second[0]]},'known_consequences':{'active_slot_options':[first,second]}}]
    wire=build_decision_wire(obs,expand_battle_pairs=True)
    assert len(wire.options)==3
    assert wire.original_observation==obs
    decoded=[wire.decode({'option':i,'text':'','decision_explanation':'Choose each slot'})['arguments'] for i in range(1,4)]
    assert {'choices':[first[1],second[0]]} in decoded
    assert {'choices':[first[0],second[1]]} in decoded
    assert {'choices':[first[1],second[1]]} not in decoded


def test_invalid_response_protocol_rejected():
    with pytest.raises(ProviderError,match='response protocol'):
        LocalModelConfig('http://127.0.0.1:1','test',response_protocol='unknown').validate()
