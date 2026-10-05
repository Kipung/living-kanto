"""Shared contract primitives: versioning, canonical hashing, validation helpers.

Every Living Kanto wire object is versioned and canonically hashable so that
replay can verify state hashes without any model call (PROJECT_GUIDE section 8).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

CONTRACTS_VERSION = 1
SUPPORTED_CONTRACT_VERSIONS = frozenset({1})


class ContractError(ValueError):
    """Raised when a wire contract is malformed or out of range."""


def canonical_json(value: Any) -> str:
    """Deterministic JSON: sorted keys, no incidental whitespace, non-ASCII preserved.

    Non-finite floats are rejected: NaN/Infinity have no canonical JSON encoding,
    and letting them through would make state hashes unreproducible.
    """
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
            default=_canonical_default,
        )
    except ValueError as exc:  # json's ValueError is about our contract domain
        raise ContractError(f"value is not canonically encodable: {exc}") from exc


def _canonical_default(value: Any) -> Any:
    if isinstance(value, frozenset) or isinstance(value, set):
        return sorted(canonical_json(v) for v in value)
    if isinstance(value, tuple):
        return list(value)
    if hasattr(value, "to_dict"):
        return value.to_dict()
    raise ContractError(f"cannot canonically encode {type(value).__name__}")


def content_hash(value: Any) -> str:
    """SHA-256 of the canonical JSON encoding; the unit of replay verification."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def require_id(value: Any, field_name: str) -> str:
    text = str(value if value is not None else "").strip()
    if not ID_PATTERN.match(text):
        raise ContractError(
            f"{field_name} must match ^[a-z][a-z0-9_-]{{0,63}}$ (got {value!r})"
        )
    return text


def require_string(value: Any, field_name: str, *, max_len: int = 4000) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    text = value.strip()
    if not text:
        raise ContractError(f"{field_name} must not be empty")
    if len(text) > max_len:
        raise ContractError(f"{field_name} must be at most {max_len} characters")
    return text


def require_exact_int(
    value: Any,
    field_name: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    """Strict JSON-integer check: no bool, no float, no string coercion.

    Policy for elapsed seconds: a persisted duration must arrive as a JSON
    integer. ``10.0`` is a JSON *number*, not an integer, and
    ``2.5`` would silently lose half a second under ``int()``; both are rejected
    outright rather than coerced. Strings such as ``"5"`` are rejected too, so a
    mis-typed client surfaces as an error instead of being repaired silently.
    Producers control these fields and can always send an integer.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError(f"{field_name} must be an integer, got {value!r}")
    if minimum is not None and value < minimum:
        raise ContractError(f"{field_name} must be >= {minimum}, got {value}")
    if maximum is not None and value > maximum:
        raise ContractError(f"{field_name} must be <= {maximum}, got {value}")
    return value


def require_int(value: Any, field_name: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ContractError(f"{field_name} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{field_name} must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise ContractError(f"{field_name} must be between {minimum} and {maximum}")
    return parsed


def require_number(value: Any, field_name: str, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise ContractError(f"{field_name} must be a number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{field_name} must be a number") from exc
    if not minimum <= parsed <= maximum:
        raise ContractError(f"{field_name} must be between {minimum} and {maximum}")
    return parsed


def require_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ContractError(f"{field_name} must be a boolean")
    return value


def require_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ContractError(f"{field_name} must be an object")
    return {str(k): v for k, v in value.items()}


def require_list(value: Any, field_name: str, *, max_items: int = 512) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ContractError(f"{field_name} must be an array")
    if len(value) > max_items:
        raise ContractError(f"{field_name} must contain at most {max_items} items")
    return list(value)


def require_hash(value: Any, field_name: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA256_PATTERN.match(text):
        raise ContractError(f"{field_name} must be a lowercase sha256 hex digest")
    return text


@dataclass(slots=True)
class Contract:
    """Base for every versioned wire object."""

    schema_version: int = CONTRACTS_VERSION

    def to_dict(self) -> dict[str, Any]:
        raise NotImplementedError

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Contract":
        raise NotImplementedError

    def check_version(self) -> int:
        version = require_int(
            self.schema_version,
            "schema_version",
            minimum=1,
            maximum=CONTRACTS_VERSION,
        )
        if version not in SUPPORTED_CONTRACT_VERSIONS:
            raise ContractError(
                f"{self.contract_kind()} schema_version {version} is not supported "
                f"(supported: {sorted(SUPPORTED_CONTRACT_VERSIONS)})"
            )
        return version

    def digest(self) -> str:
        return content_hash(self.to_dict())


def as_plain_dict(value: Any) -> dict[str, Any]:
    """Deep-copy a contract payload into plain mutable dicts/lists.

    Unlike to_dict()'s shallow copies, mutating the result can never reach
    back into the source contract's nested mappings.
    """
    parsed = json.loads(canonical_json(value))
    if not isinstance(parsed, dict):
        raise ContractError("as_plain_dict requires a mapping")
    return parsed


def as_versioned_dict(data: Mapping[str, Any], *, kind: str) -> dict[str, Any]:
    """Copy a payload and assert it declares the kind the caller expects."""
    payload = require_mapping(data, kind)
    actual = payload.get("kind")
    if actual is not None and actual != kind:
        raise ContractError(f"expected kind {kind!r}, got {actual!r}")
    return payload
