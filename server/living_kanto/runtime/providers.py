"""Local inference configuration; endpoint secrets never enter portable events."""
from __future__ import annotations

import ipaddress
import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from .decision_wire import build_decision_wire, DecisionWireError


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
        self.protocol = config.protocol if config.response_protocol == "canonical" else config.protocol + ":numbered"
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def complete(self, observation: dict, correction: str | None = None) -> str:
        self.config.validate()
        wire = None
        if self.config.response_protocol == 'numbered':
            try:wire = build_decision_wire(observation, expand_battle_pairs=True)
            except DecisionWireError as exc:raise ProviderError(str(exc)) from exc
        observation_json = wire.serialize() if wire else json.dumps(observation, ensure_ascii=False)
        if len(observation_json) > 131_072:
            raise ProviderError("Private observation exceeds inference input limit; compact memory/context before retrying")
        messages = [{"role": "system", "content": (
            "You are this individual human in Living Kanto. Choose one engine legal action using only this private observation. "
            "Return only a JSON object with action, arguments, decision_explanation. Explanation must be non-empty. "
            "Use exact offered arguments; text placeholders permit your own text up to 200 characters. "
            "Do not invent rewards or world facts. No arbitrary tools are available.")},
            {"role": "user", "content": observation_json}]
        if correction:
            messages.append({"role": "user", "content": "Your previous response was rejected: " + correction + ". Return a corrected JSON action."})
        if wire:
            messages[0]['content'] = (
                "You are this individual human in Living Kanto. Use only your private facts, memories, personality and goals to choose one useful offered option. "
                "Return exactly option (integer), text (string), decision_explanation (one short clause, at most80 characters). "
                "text must be empty unless the selected arguments.text explicitly offers a text placeholder; then write your own nonempty text of at most200 characters. "
                "All other action arguments are fixed. When a goal is already recorded, choose a useful legal step towards it; update the goal only when facts justify a genuine change, never merely to restate it. "
                "Prefer a useful existing journey over tile micromanagement when it serves your goal. Do not invent world facts. Return JSON only.")
            if correction:messages[-1]['content']='Your previous proposal was rejected: '+correction+'. Return a corrected numbered choice with option, text, decision_explanation.'
        schema = None
        if wire:
            schema = wire.response_schema
            schema['properties']['decision_explanation']['maxLength'] = 80
            schema.pop('anyOf', None)  # Benchmarked flat grammar; decoder still enforces conditional text.
        config = self.config
        if config.protocol == "openai":
            path = "/chat/completions" if config.endpoint.rstrip("/").endswith("/v1") else "/v1/chat/completions"
            payload = {"model": config.model, "messages": messages, "temperature": 0.7,
                       "max_tokens": config.max_tokens, "stream": False,
                       "response_format": {"type": "json_schema", "json_schema": {"name":"private_choice", "schema":schema}} if wire else {"type": "json_object"},
                       "chat_template_kwargs": {"enable_thinking": config.enable_thinking}}
        else:
            path = "/api/chat"
            payload = {"model": config.model, "messages": messages, "format": schema if wire else "json", "stream": False,
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

        if wire:
            try:return json.dumps(wire.decode(text), ensure_ascii=False)
            except DecisionWireError as exc:
                raise NumberedDecisionError(str(exc)) from exc
        return text
