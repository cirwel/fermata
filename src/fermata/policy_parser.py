"""Parser for the v0 authority-policy surface (curly-brace block syntax).

Lowers an authority-authored ``scope { ... }`` block into a canonical IR Scope
record that validates against
``references/governed-effect-ir-v0.schema.json``.

Grammar (line-oriented, deliberately small):

::

    scope NAME {
      resource KIND "TARGET"
      capability NAME on "PATTERN"
      policy EFFECT if CONDITION
      approval require AUTHORITY if CONDITION
      audit retain FIELD, FIELD, ...
    }

The parser does not interpret conditions; conditions are stored as opaque
strings on the IR record. The runtime decides what conditions mean.

Per charter ``docs/charter-v0.md`` §2 non-goals and §13 cut-line: this is
not a full policy language. It is the smallest parser that proves an
authority-policy example can lower into a canonical IR Scope record. The
parser deliberately has no grant construct ("approval grant ..." or
"approve ...") — the authority-policy surface declares *requirements*; only
the runtime, given an explicit approval decision, produces an approved
state.
"""

from __future__ import annotations

import re
from typing import Any


_RESOURCE_KINDS = frozenset(
    {"file", "db", "message", "memory", "network", "tool"}
)
_POLICY_EFFECTS = frozenset(
    {"allow", "deny", "pause", "require_approval", "require_evidence"}
)
_AUTHORITIES = frozenset({"performer", "council", "runtime", "none"})
_AUDIT_FIELDS = frozenset(
    {
        "trace",
        "dry_run",
        "approval",
        "input_hash",
        "output_hash",
        "actor",
        "scope",
        "adapter_ack",
        "verification",
    }
)

_SCOPE_HEADER_RE = re.compile(
    r"^\s*scope\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{\s*$"
)
_RESOURCE_RE = re.compile(r'^\s*resource\s+(\S+)\s+"([^"]+)"\s*$')
_CAPABILITY_RE = re.compile(r'^\s*capability\s+(\S+)\s+on\s+"([^"]+)"\s*$')
_POLICY_RE = re.compile(r"^\s*policy\s+(\S+)\s+if\s+(.+?)\s*$")
_APPROVAL_RE = re.compile(r"^\s*approval\s+require\s+(\S+)\s+if\s+(.+?)\s*$")
_AUDIT_RE = re.compile(r"^\s*audit\s+retain\s+(.+?)\s*$")
_CLOSE_RE = re.compile(r"^\s*\}\s*$")


class PolicyParseError(ValueError):
    """Raised when an authority-policy block fails to parse."""


def parse_policy_block(text: str) -> dict[str, Any]:
    """Parse an authority-policy block into a canonical IR Scope record.

    The returned dict is shaped to match the ``Scope`` definition in
    ``references/governed-effect-ir-v0.schema.json``: it carries
    ``schema_version``, ``record_type: "scope"``, ``scope_id``, and the
    typed lists for resources, capabilities, policies, approvals, and
    audit retention.

    Conditions on policy and approval rules are stored as opaque strings.
    The runtime, not the parser, decides what they mean.

    Raises ``PolicyParseError`` on any syntax error, with line number.
    """

    lines = text.splitlines()
    scope_id: str | None = None
    resources: list[dict[str, Any]] = []
    capabilities: list[dict[str, Any]] = []
    policies: list[dict[str, Any]] = []
    approvals: list[dict[str, Any]] = []
    audit: dict[str, Any] = {}
    in_scope = False
    closed = False

    for lineno, raw_line in enumerate(lines, start=1):
        line = raw_line.split("//", 1)[0].rstrip()
        if not line.strip():
            continue

        if closed:
            raise PolicyParseError(
                f"line {lineno}: unexpected content after the scope block was "
                "closed; a policy block must contain exactly one "
                "'scope NAME { ... }' block"
            )

        if not in_scope:
            m = _SCOPE_HEADER_RE.match(line)
            if not m:
                raise PolicyParseError(
                    f"line {lineno}: expected 'scope NAME {{', got: {line!r}"
                )
            scope_id = m.group(1)
            in_scope = True
            continue

        if _CLOSE_RE.match(line):
            in_scope = False
            closed = True
            continue

        m = _RESOURCE_RE.match(line)
        if m:
            kind, target = m.group(1), m.group(2)
            if kind not in _RESOURCE_KINDS:
                raise PolicyParseError(
                    f"line {lineno}: unknown resource kind {kind!r}; "
                    f"expected one of {sorted(_RESOURCE_KINDS)}"
                )
            resources.append({"kind": kind, "target": target})
            continue

        m = _CAPABILITY_RE.match(line)
        if m:
            cap_name, pattern = m.group(1), m.group(2)
            if "." not in cap_name:
                raise PolicyParseError(
                    f"line {lineno}: capability {cap_name!r} must be of "
                    "the form KIND.MODE (e.g. file.write)"
                )
            kind_prefix, mode = cap_name.split(".", 1)
            if kind_prefix not in _RESOURCE_KINDS:
                raise PolicyParseError(
                    f"line {lineno}: capability prefix {kind_prefix!r} is "
                    "not a known resource kind"
                )
            capabilities.append(
                {
                    "name": cap_name,
                    "resource_kind": kind_prefix,
                    "mode": mode,
                    "allow": [pattern],
                }
            )
            continue

        m = _POLICY_RE.match(line)
        if m:
            effect, condition = m.group(1), m.group(2)
            if effect not in _POLICY_EFFECTS:
                raise PolicyParseError(
                    f"line {lineno}: unknown policy effect {effect!r}; "
                    f"expected one of {sorted(_POLICY_EFFECTS)}"
                )
            policies.append(
                {
                    "id": f"policy_{len(policies) + 1:03d}",
                    "effect": effect,
                    "condition": condition,
                }
            )
            continue

        m = _APPROVAL_RE.match(line)
        if m:
            authority, condition = m.group(1), m.group(2)
            if authority not in _AUTHORITIES:
                raise PolicyParseError(
                    f"line {lineno}: unknown approval authority "
                    f"{authority!r}; expected one of {sorted(_AUTHORITIES)}"
                )
            approvals.append({"authority": authority, "condition": condition})
            continue

        m = _AUDIT_RE.match(line)
        if m:
            fields_raw = m.group(1)
            fields = [f.strip() for f in fields_raw.split(",") if f.strip()]
            for f in fields:
                if f not in _AUDIT_FIELDS:
                    raise PolicyParseError(
                        f"line {lineno}: unknown audit field {f!r}; "
                        f"expected one of {sorted(_AUDIT_FIELDS)}"
                    )
            audit["retain"] = fields
            continue

        raise PolicyParseError(
            f"line {lineno}: unrecognized statement: {line!r}"
        )

    if scope_id is None:
        raise PolicyParseError(
            "policy block must contain a 'scope NAME { ... }' block"
        )
    if not closed:
        raise PolicyParseError("scope block was not closed with '}'")
    if not resources:
        raise PolicyParseError("scope must declare at least one resource")
    if not capabilities:
        raise PolicyParseError("scope must declare at least one capability")

    record: dict[str, Any] = {
        "schema_version": "0.1",
        "record_type": "scope",
        "scope_id": scope_id,
        "resources": resources,
        "capabilities": capabilities,
    }
    if policies:
        record["policies"] = policies
    if approvals:
        record["approvals"] = approvals
    if audit:
        record["audit"] = audit

    return record


def parse_agent_proposal_json(json_text: str) -> dict[str, Any]:
    """Load an agent-emitted JSON proposal into a raw record dict.

    Agents emit JSON that is meant to validate as a ``Proposal`` record
    against ``references/governed-effect-ir-v0.schema.json``. This helper
    is a thin wrapper around ``json.loads`` that exists so callers can
    treat the agent surface symmetrically with the authority surface
    (``parse_policy_block``).

    This helper does **not** validate the record against the canonical
    schema, and it does **not** enforce ``additionalProperties: false``;
    it returns whatever JSON object the agent supplied. It is therefore
    *not* a trust boundary. Schema validation happens in the golden-check
    suite (``golden_checks.validate_record``); the runtime trust boundary
    is ``runtime_api.proposal_from_record``, which lowers the dict into a
    typed ``Proposal`` by reading only known fields, so an agent cannot
    self-declare a committed effect by attaching extra fields — a
    ``CommittedEffect`` requires adapter acknowledgement and verification
    that only the runtime evaluator can supply.

    Raises ``ValueError`` on JSON decode error.
    """

    import json

    return json.loads(json_text)
