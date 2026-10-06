"""Local inference configuration; endpoint secrets never enter portable events."""
from __future__ import annotations

import ipaddress
import json
import os
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from .decision_wire import build_decision_wire, DecisionWireError, TEXT_PLACEHOLDERS, _strict_object


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


class LocalModelProvider:
    def __init__(self, config: LocalModelConfig):
        self.config = config.validate()
        self.model_id = config.model
        self.protocol = config.protocol if config.response_protocol == "canonical" else config.protocol + ":numbered-staged"
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        self._lanes = ()
        if config.additional_endpoints:
            self._lanes = tuple(LocalModelProvider(replace(config, endpoint=endpoint, additional_endpoints=()))
                                for endpoint in (config.endpoint, *config.additional_endpoints))
            self.protocol += ':pool'
            self._lane_lock = threading.Lock()
            self._lane_cursor = 0
            self._lane_active = [0] * len(self._lanes)
            self._lane_completed = [0] * len(self._lanes)
            self._lane_failed = [0] * len(self._lanes)

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
            'Return only a JSON object with action, arguments, decision_explanation. Explanation must be non-empty. '
            'Use exact offered arguments; text placeholders permit your own text up to 200 characters. '
            'Do not invent rewards or world facts. No arbitrary tools are available.')},
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
            'Return exactly option (integer), decision_explanation (one short clause, at most80 characters). Do not include text or other fields. '
            'All action arguments are fixed; when the chosen option offers a text placeholder, you will write its text in the next request. '
            'When a goal is already recorded, choose a useful legal step towards it; update the goal only when facts justify a genuine change, never merely to restate it. '
            'Prefer a useful existing journey over tile micromanagement when it serves your goal. Do not invent world facts. Return JSON only.')},
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
            text_schema={'type':'object','properties':{'text':{'type':'string','minLength':1,'maxLength':200}},'required':['text'],'additionalProperties':False}
            text_messages=[{'role':'system','content':(
                'You are the same individual human, completing the option you just chose. Use only your own private facts, memories and personality. '
                'Write the actual text required by that selected action. Return exactly one JSON field text, a nonempty string of at most200 characters. '
                'Do not choose another option or invent world facts.')},
                {'role':'user','content':observation_json},
                {'role':'user','content':'Your selected option and explanation: '+json.dumps(choice,ensure_ascii=False)}]
            if correction:text_messages.append({'role':'user','content':'The previous decision was rejected: '+correction+'. Correct the text if applicable.'})
            text=self._decision_object(self._infer(text_messages,text_schema),['text'])['text']
        try:return json.dumps(wire.decode({**choice,'text':text}),ensure_ascii=False)
        except DecisionWireError as exc:raise NumberedDecisionError(str(exc)) from exc

    def _infer(self, messages, schema=None):
        config = self.config
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
            text = result["choices"][0]["message"]["content"] if config.protocol == "openai" else result["message"]["content"]
            if not isinstance(text, str):
                raise ProviderError("Model response has no text content")
        except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            # Never include URL, credentials, or response body in persisted/status errors.
            raise ProviderError("Local model request failed or returned an unsupported response") from exc

        return text
