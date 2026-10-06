"""Local inference configuration; endpoint secrets never enter portable events."""
from __future__ import annotations

import hashlib
from collections import OrderedDict
import ipaddress
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from .decision_wire import build_decision_wire, DecisionWireError, TEXT_PLACEHOLDERS, _strict_object
from ..simulation.decision_awareness import GUIDANCE as AWARENESS_GUIDANCE


class ProviderError(RuntimeError):
    pass


class NumberedDecisionError(ProviderError):
    """Safe fixed decoder reason, eligible for the single corrective retry."""
    pass


@dataclass(frozen=True)
class LocalModelConfig:
    endpoint: str
    model: str
    protocol: str = "openai"
    timeout_seconds: float = 60
    max_tokens: int = 512
    api_key: str = ""
    enable_thinking: bool = False
    response_protocol: str = "canonical"
    additional_endpoints: tuple[str, ...] = ()

    @classmethod
    def from_env(cls):
        endpoint = os.environ.get("LIVING_KANTO_MODEL_ENDPOINT", "")
        model = os.environ.get("LIVING_KANTO_MODEL", "")
        if not endpoint or not model:
            raise ProviderError("Configure LIVING_KANTO_MODEL_ENDPOINT and LIVING_KANTO_MODEL to run AI humans")
        return cls(endpoint, model, os.environ.get("LIVING_KANTO_MODEL_PROTOCOL", "openai"),
                   float(os.environ.get("LIVING_KANTO_MODEL_TIMEOUT", "60")),
                   int(os.environ.get("LIVING_KANTO_MODEL_MAX_TOKENS", "512")),
                   os.environ.get("LIVING_KANTO_MODEL_API_KEY", ""),
                   os.environ.get("LIVING_KANTO_MODEL_ENABLE_THINKING", "false").lower() in {"1", "true", "yes"},
                   os.environ.get("LIVING_KANTO_RESPONSE_PROTOCOL", "canonical"))

    def validate(self):
        if not isinstance(self.additional_endpoints, (tuple, list)) or len(self.additional_endpoints) > 1 or any(not isinstance(endpoint, str) for endpoint in self.additional_endpoints):
            raise ProviderError("Configure at most one additional local model endpoint")
        if any(endpoint.rstrip('/') == self.endpoint.rstrip('/') for endpoint in self.additional_endpoints):
            raise ProviderError("Additional local model endpoint must be distinct")
        for endpoint in self.additional_endpoints:
            replace(self, endpoint=endpoint, additional_endpoints=()).validate()
        url = urllib.parse.urlsplit(self.endpoint)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ProviderError("Model endpoint must be a local HTTP(S) base URL")
        if self.protocol not in {"openai", "ollama"} or not self.model.strip():
            raise ProviderError("Choose openai or ollama and a non-empty local model")
        if not 0 < self.timeout_seconds <= 600 or not 1 <= self.max_tokens <= 8192:
            raise ProviderError("Invalid inference timeout or response token limit")
        if self.response_protocol not in {"canonical", "numbered"}:
            raise ProviderError("Choose canonical or numbered response protocol")
        try:
            addresses = socket.getaddrinfo(url.hostname, url.port or (443 if url.scheme == "https" else 80))
        except OSError as exc:
            raise ProviderError("Local model hostname could not be resolved") from exc
        shared = ipaddress.ip_network("100.64.0.0/10")
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if not (ip.is_loopback or ip.is_private or ip in shared):
                raise ProviderError("Cloud/public model endpoints are prohibited for runtime humans")
        return self


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ProviderError("Model endpoint redirects are prohibited")


CARE_DECISION_GUIDANCE = ('Assess care_summary alongside your ambitions: fainted Pokémon cannot battle, and injuries, status conditions or depleted PP affect your party. ' 'A commitment can be interrupted for care or real service responsibilities. Consider the offered care, supplies, service and travel options; you still choose whether and when to use them. ' 'Healing requires a request and actual staff service; conversation does not heal a party or serve a customer. ' 'Rewording the same unanswered request is not a new result. Compare observed replies and recent outcomes; consider a different practical action when the conversation is not helping. ')

class LocalModelProvider:
    def __init__(self, config: LocalModelConfig):
        self.config = config.validate()
        self.model_id = config.model
        self.protocol = config.protocol if config.response_protocol == "canonical" else config.protocol + ":numbered-staged"
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        self._token_lock = threading.Lock()
        self._token_counts = OrderedDict()
        self._server_context_limit = 16384
        self._lanes = ()
        self._trace_sink = None
        self._trace_setup_error = None
        self._trace_local = threading.local()
        if config.additional_endpoints:
            self._lanes = tuple(LocalModelProvider(replace(config, endpoint=endpoint, additional_endpoints=()))
                                for endpoint in (config.endpoint, *config.additional_endpoints))
            self.protocol += ':pool'
            self._lane_lock = threading.Lock()
            self._lane_cursor = 0
            self._lane_active = [0] * len(self._lanes)
            self._lane_completed = [0] * len(self._lanes)
            self._lane_failed = [0] * len(self._lanes)

    def configure_trace(self, directory, run_id):
        from .inference_trace import InferenceTrace
        try:
            sink = InferenceTrace(directory, run_id)
        except Exception as exc:
            self._trace_sink = None
            self._trace_setup_error = type(exc).__name__
            for lane in self._lanes:
                lane._trace_sink = None
                lane._trace_setup_error = self._trace_setup_error
            return None
        self._trace_setup_error = None
        self._trace_sink = sink
        for lane in self._lanes:
            lane._trace_sink = sink
        return sink

    def trace_status(self):
        if self._trace_sink is None:
            return {'enabled': False, 'audit_error': self._trace_setup_error}
        try:
            return self._trace_sink.status()
        except Exception as exc:
            self._trace_sink.audit_error = type(exc).__name__
            return {'enabled': True, 'audit_error': type(exc).__name__}

    def record_trace_outcome(self, observation, response, outcome, event_id=None, reason=None, state_version=None):
        from .inference_trace import digest
        if self._trace_sink is None:
            return False
        try:
            try: choice = json.loads(response) if isinstance(response, str) else response
            except ValueError: choice = response
            return self._trace_sink.outcome(observation.get('human_id'), digest(observation), digest(choice), outcome, event_id, reason, state_version)
        except Exception as exc:
            self._trace_sink.audit_error = type(exc).__name__
            return False

    def lane_status(self):
        if not self._lanes:
            return []
        with self._lane_lock:
            return [{'lane': index + 1, 'active': self._lane_active[index],
                     'completed': self._lane_completed[index], 'failed': self._lane_failed[index]}
                    for index in range(len(self._lanes))]

    def _pooled_complete(self, observation, correction):
        with self._lane_lock:
            order = [(self._lane_cursor + offset) % len(self._lanes) for offset in range(len(self._lanes))]
            lane = min(order, key=lambda index: self._lane_active[index])
            self._lane_active[lane] += 1
            self._lane_cursor = (lane + 1) % len(self._lanes)
        succeeded = False
        try:
            # One member owns the entire staged decision. Endpoint errors
            # propagate directly; no failover or hidden replacement request.
            result = self._lanes[lane].complete(observation, correction)
            succeeded = True
            return result
        finally:
            with self._lane_lock:
                self._lane_active[lane] -= 1
                if succeeded:
                    self._lane_completed[lane] += 1
                else:
                    self._lane_failed[lane] += 1

    def complete(self, observation: dict, correction: str | None = None) -> str:
        if self._lanes:
            return self._pooled_complete(observation, correction)
        if self._trace_sink is None:
            return self._complete_untraced(observation, correction)
        from .inference_trace import digest
        record = {'human_id': observation.get('human_id'), 'observation_version': observation.get('observation_version', observation.get('state_version')),
                  'observation_hash': digest(observation), 'model_id': self.model_id, 'protocol': self.protocol,
                  'corrective_retry': correction is not None, 'stages': [], 'outcome': 'proposed'}
        self._trace_local.record = record
        started = time.monotonic()
        try:
            response = self._complete_untraced(observation, correction)
            record['canonical_response'] = response
            try: normalized = json.loads(response)
            except ValueError: normalized = response
            record['response_hash'] = digest(normalized)
            return response
        except Exception as exc:
            record['outcome'] = 'provider_rejected'
            record['error_type'] = type(exc).__name__
            raise
        finally:
            record['decision_seconds'] = time.monotonic() - started
            self._trace_local.record = None
            try:
                # Credentials and configured URLs must never enter even an audit
                # if a malformed model response happens to echo them.
                secrets = [self.config.api_key, self.config.endpoint, *self.config.additional_endpoints]
                redacted = [False]
                def redact(value):
                    if isinstance(value, str):
                        for secret in secrets:
                            if secret and secret in value:
                                redacted[0] = True
                                value = value.replace(secret, '[redacted configuration]')
                        return value
                    if isinstance(value, list): return [redact(v) for v in value]
                    if isinstance(value, dict): return {k: redact(v) for k, v in value.items()}
                    return value
                safe_record = redact(record)
                if redacted[0]: safe_record['redacted_config_values'] = True
                self._trace_sink.append(safe_record)
            except Exception as exc:
                self._trace_sink.audit_error = type(exc).__name__

    def _complete_untraced(self, observation, correction):
        self.config.validate()
        wire = None
        if self.config.response_protocol == 'numbered':
            try:wire = build_decision_wire(observation, expand_battle_pairs=True)
            except DecisionWireError as exc:raise ProviderError(str(exc)) from exc
        observation_json = wire.serialize() if wire else json.dumps(observation, ensure_ascii=False)
        if len(observation_json)>131_072:
            raise ProviderError('Private observation exceeds inference input limit; compact memory/context before retrying')
        if wire:return self._numbered(wire, observation_json, correction)
        messages=[{'role':'system','content':(
            'You are this individual human in Living Kanto. Choose one engine legal action using only this private observation. '
            'If self_state.cognitive_mode is background_deliberation, follow cognition_instruction: your response records only a conditional thought while execution continues. '
            'Otherwise check self_state.cognition for earlier suggestions and re-evaluate them against present legal actions. '
            'Return only a JSON object with action, arguments, decision_explanation. Explanation must be non-empty. '
            'Use exact offered arguments; text placeholders permit your own text up to 200 characters. '
            'Do not invent rewards or world facts. No arbitrary tools are available. '+CARE_DECISION_GUIDANCE+AWARENESS_GUIDANCE)},
            {'role':'user','content':observation_json}]
        if correction:messages.append({'role':'user','content':'Your previous response was rejected: '+correction+'. Return a corrected JSON action.'})
        return self._infer(messages)

    @staticmethod
    def _decision_object(raw, fields):
        try:result=json.loads(raw,object_pairs_hook=_strict_object)
        except (ValueError,TypeError) as exc:
            raise NumberedDecisionError('Response must be one JSON object without duplicate keys') from exc
        if not isinstance(result,dict) or set(result)!=set(fields):
            raise NumberedDecisionError('Response must contain exactly '+', '.join(fields))
        return result

    def _numbered(self, wire, observation_json, correction):
        schema=wire.response_schema
        schema.pop('anyOf',None)
        schema['properties'].pop('text')
        schema['properties']['decision_explanation']['maxLength']=80
        schema['required']=['option','decision_explanation']
        messages=[{'role':'system','content':(
            'You are this individual human in Living Kanto. Use only your private facts, memories, personality and goals to choose one useful offered option. '
            'If self_state.cognitive_mode is background_deliberation, follow cognition_instruction: your response records only a conditional thought while execution continues. '
            'Otherwise check self_state.cognition for earlier suggestions and re-evaluate them against present legal actions. '
            'Return exactly option (integer), decision_explanation (one short clause, at most80 characters). Do not include text or other fields. '
            'All action arguments are fixed; when the chosen option offers a text placeholder, you will write its text in the next request. '
            'Your individual_life contains your aspiration, current commitment and recent decisions. If you have no active commitment and no immediate care or service need, consider set_commitment for one concrete next task grounded in your own facts, values, relationships and responsibilities. '
            'Inspect self_state.continuity before choosing. Select plan_next_step to name a concrete offered action and its purpose; then execute that action across decisions. A planned step does not perform it. '
            'The engine records factual step completion; it does not award goal completion. When blocked by duty, missing options, or interruption, pause_task or abandon_task with a reason. resume_task continues the same step. '
            'If you choose another activity, your decision_explanation must explain why you changed approach or interrupted the step. Do not claim an exit approach left the map when changes_map is false. '
            'Use respond_to to answer, acknowledge, or decline a specific received speech message. Read the speaker’s actual question; your own topic is not their question. Nobody is obliged to reply or remain in conversation. '
            'Repeated remember or set_goal text is bookkeeping, not evidence of new observations or training. Prefer a feasible action or explain that progress is blocked. '
            'Keep pursuing an active commitment across decisions. Use observed results to assess progress; repeating a conversation is not evidence of learning or success. '
            'Inspect self_state.behavior_feedback for factual recent outcomes, warnings and available pathways. Compare what actually changed with your commitment; reconsider your method when the results do not support progress. '
            'Use the offered known_consequences to understand destinations and services. You may continue a conversation when it serves a concrete purpose; choose your own next method using the evidence. '
            'Your private conversation_context contains messages you actually received. When useful, acknowledge or answer them; you may decline or disengage. Claims from other speakers are reported speech, not established facts or new aspirations for you. '
            'Use complete_commitment only for an evidenced result, or abandon_commitment to explain why it no longer fits. These are your assessments and grant no rewards. '
            'Inherited ambitions may not fit your role or responsibilities. You may revise them using set_aspiration; ground your purpose in your actual life, not nonexistent clinical patients, family facts or completed achievements. '
            'Use set_aspiration to express a personal future and explain why it matters; do not merely repeat a generic inherited goal. Different people need not compete. Do not invent family, obligations or achievements. '
            'Choose ordinary actions to carry out the commitment; reflect only when needed, rather than endlessly rewriting plans. '
            +CARE_DECISION_GUIDANCE+AWARENESS_GUIDANCE+'Prefer a useful existing journey over tile micromanagement when it serves your goal. Do not invent world facts. Return JSON only.')},
            {'role':'user','content':observation_json}]
        if correction:messages.append({'role':'user','content':'Your previous decision was rejected: '+correction+'. Correct your choice or required text. This request returns only option and decision_explanation.'})
        choice=self._decision_object(self._infer(messages,schema),['option','decision_explanation'])
        number=choice['option'];reason=choice['decision_explanation']
        if type(number) is not int or not 1<=number<=len(wire.options):
            raise NumberedDecisionError('Option is outside the offered menu')
        if not isinstance(reason,str) or not reason.strip() or len(reason)>80:
            raise NumberedDecisionError('A non-empty explanation of at most 80 characters is required')
        selected=wire.options[number-1]
        placeholder=selected['arguments'].get('text')
        text=''
        if isinstance(placeholder,str) and placeholder in TEXT_PLACEHOLDERS:
            from .decision_wire import option_text_limit
            text_limit=option_text_limit(selected)
            text_schema={'type':'object','properties':{'text':{'type':'string','minLength':1,'maxLength':text_limit}},'required':['text'],'additionalProperties':False}
            text_messages=[{'role':'system','content':(
                'You are the same individual human, completing the option you just chose. Use only your own private facts, memories and personality. '
                f'Write the actual text required by that selected action. Return exactly one JSON field text, a nonempty string of at most {text_limit} characters. '
                'Do not choose another option or invent world facts.')},
                {'role':'user','content':observation_json},
                {'role':'user','content':'Your selected option and explanation: '+json.dumps(choice,ensure_ascii=False)}]
            if correction:text_messages.append({'role':'user','content':'The previous decision was rejected: '+correction+'. Correct the text if applicable.'})
            text=self._decision_object(self._infer(text_messages,text_schema),['text'])['text']
        try:return json.dumps(wire.decode({**choice,'text':text}),ensure_ascii=False)
        except DecisionWireError as exc:raise NumberedDecisionError(str(exc)) from exc

    def _count_context(self, messages):
        # vLLM exposes its actual chat-template tokenizer. Other local servers
        # use a conservative UTF-8 byte estimate rather than a chars/4 guess.
        key=hashlib.sha256(json.dumps(messages,sort_keys=True).encode()).hexdigest()
        with self._token_lock:
            cached=self._token_counts.get(key)
        if cached is not None:return cached
        if os.environ.get('LK_TOKENIZER_PREFLIGHT')=='1' and self.config.protocol=='openai':
            endpoint=self.config.endpoint.rstrip('/')
            if endpoint.endswith('/v1'):endpoint=endpoint[:-3]
            payload={'model':self.model_id,'messages':messages,'add_generation_prompt':True,
                     'chat_template_kwargs':{'enable_thinking':self.config.enable_thinking}}
            headers={'Content-Type':'application/json'}
            if self.config.api_key:headers['Authorization']='Bearer '+self.config.api_key
            request=urllib.request.Request(endpoint+'/tokenize',json.dumps(payload).encode(),headers)
            try:
                with self._opener.open(request,timeout=min(10,self.config.timeout_seconds)) as response:
                    result=json.loads(response.read(1_048_576))
                if type(result.get('count')) is int and result['count']>=0:
                    if type(result.get('max_model_len')) is int and result['max_model_len']>0:self._server_context_limit=result['max_model_len']
                    with self._token_lock:
                        self._token_counts[key]=result['count']
                        if len(self._token_counts)>64:self._token_counts.popitem(last=False)
                    return result['count']
            except (OSError,ValueError,KeyError,TypeError):pass
        return sum(len(str(m.get('content','')).encode('utf-8')) for m in messages)+2048

    def _infer(self, messages, schema=None):
        config = self.config
        from .context_budget import fit_messages, ContextBudgetError
        try:
            self._count_context(messages)
            limit=min(int(os.environ.get('LK_CONTEXT_TOKENS','16384')),self._server_context_limit)
            messages,budget=fit_messages(messages,self._count_context,limit,config.max_tokens)
        except (ValueError,ContextBudgetError) as exc:raise ProviderError(str(exc)) from exc
        trace = getattr(self._trace_local, 'record', None)
        stage = None
        if trace is not None:
            stage = {'messages': messages, 'messages_hash': __import__('living_kanto.runtime.inference_trace', fromlist=['digest']).digest(messages),
                     'schema': schema, 'budget': budget, 'generation': {'max_tokens': config.max_tokens, 'temperature': 0.7 if config.protocol == 'openai' else None, 'enable_thinking': config.enable_thinking}, 'stage': 'text' if schema and schema.get('required') == ['text'] else 'choice'}
            trace['stages'].append(stage)
        inference_started = time.monotonic()
        if config.protocol == "openai":
            path = "/chat/completions" if config.endpoint.rstrip("/").endswith("/v1") else "/v1/chat/completions"
            payload = {"model": config.model, "messages": messages, "temperature": 0.7,
                       "max_tokens": config.max_tokens, "stream": False,
                       "response_format": {"type": "json_schema", "json_schema": {"name":"private_choice", "schema":schema}} if schema else {"type": "json_object"},
                       "chat_template_kwargs": {"enable_thinking": config.enable_thinking}}
        else:
            path = "/api/chat"
            payload = {"model": config.model, "messages": messages, "format": schema if schema else "json", "stream": False,
                       "options": {"num_predict": config.max_tokens}}
        headers = {"Content-Type": "application/json"}
        if config.api_key:
            headers["Authorization"] = "Bearer " + config.api_key
        request = urllib.request.Request(config.endpoint.rstrip("/") + path,
                                         json.dumps(payload).encode(), headers)
        try:
            with self._opener.open(request, timeout=config.timeout_seconds) as response:
                raw = response.read(1_048_577)
            if len(raw) > 1_048_576:
                raise ProviderError("Model response exceeds size limit")
            result = json.loads(raw)
            if stage is not None:
                usage = result.get('usage')
                if not isinstance(usage, dict): usage = {}
                stage['usage'] = {key: value for key, value in usage.items() if key in {'prompt_tokens', 'completion_tokens', 'total_tokens'} and type(value) is int}
                if config.protocol == 'openai':
                    stage['finish_reason'] = result.get('choices', [{}])[0].get('finish_reason')
                else:
                    stage['finish_reason'] = result.get('done_reason')
                    stage['usage'] = {key: result[key] for key in ('prompt_eval_count', 'eval_count') if type(result.get(key)) is int}
            text = result["choices"][0]["message"]["content"] if config.protocol == "openai" else result["message"]["content"]
            if stage is not None:
                stage['raw_response'] = text
            if not isinstance(text, str):
                raise ProviderError("Model response has no text content")
        except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            # Never include URL, credentials, or response body in persisted/status errors.
            raise ProviderError("Local model request failed or returned an unsupported response") from exc

        finally:
            if stage is not None:
                stage['inference_seconds'] = time.monotonic() - inference_started
        return text
