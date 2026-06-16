"""Governed ``network.fetch`` adapter — outbound HTTP(S) GET under scope.

The first network effect Fermata governs. An agent proposes an ``intend`` with
``adapter="network"``, ``operation="fetch"``: the runtime checks the URL against
a scope allowlist, refuses private/loopback targets unless explicitly permitted,
fetches with hard timeout/size/scheme/redirect guards, persists the response to a
scoped sandbox file, and verifies by reading it back and comparing SHA-256 — the
same verification contract as the file and memory adapters.

Security posture (fail-closed). Read this before changing anything:

- URL matching is **structural**, never substring/startswith on the raw URL:
  the URL is parsed and compared by scheme + exact host + optional port + path
  prefix. Userinfo (``user@host``) is rejected outright.
- Only ``http``/``https`` schemes; only the ``GET`` method.
- Private / loopback / link-local / reserved resolutions are rejected unless the
  scope sets ``allow_private_network`` (opt-in for governing local services).
  The resolution check runs again at commit to narrow the DNS-rebinding window.
- Redirects are never followed: any 3xx is rejected.
- The response body is capped at ``scope.max_bytes`` (Content-Length checked
  early; the stream is also hard-capped). ``Accept-Encoding: identity`` is sent
  so a compressed body cannot inflate past the cap. No credential headers.
- The persisted write reuses the file adapter's O_NOFOLLOW anchored walk.

Deferred to a future version (documented, not silently missing): resolved-IP
pinning between check and connect (full DNS-rebinding immunity), per-scope
request-rate budgets, and content-type contract enforcement. (Port restriction
is enforced: a port-less allowlist entry authorizes only the scheme default.)
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from fermata.runtime_core import (
    anchored_atomic_write,
    evaluate_with_adapter,
    is_inside,
    reject,
)
from fermata.runtime_ir import (
    AdapterPreparation,
    ApprovalDecision,
    CommitEvidence,
    EffectResult,
    Intent,
    Proposal,
    RejectionReason,
    Scope,
    Trace,
    now_timestamp,
    sha256_bytes,
)

ALLOWED_SCHEMES = frozenset({"http", "https"})
ALLOWED_METHODS = frozenset({"GET"})
CONNECT_TIMEOUT_SECONDS = 5.0
READ_TIMEOUT_SECONDS = 10.0
NETWORK_STORE_DIRNAME = ".fermata-network"
_USER_AGENT = "fermata-governed-fetch/0"


def _network_store_path(scope: Scope, target: str) -> Path:
    """Resolve the scoped path the response will be persisted to.

    Mirrors ``memory_store_path``: only the store root is resolved; the leaf is
    left unresolved so the anchored O_NOFOLLOW walk in commit rejects symlinks.
    """

    target_text = target.strip()
    parts = target_text.split("/")
    if (
        not target_text
        or target_text != target
        or target_text.startswith("/")
        or target_text.endswith("/")
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ValueError("path_outside_scope")
    raw = Path(*parts)
    if raw.is_absolute():
        raise ValueError("path_outside_scope")
    store_root = (scope.sandbox_root / NETWORK_STORE_DIRNAME).resolve()
    response_path = store_root / raw
    if not is_inside(scope.sandbox_root, response_path) or not is_inside(
        store_root, response_path
    ):
        raise ValueError("path_outside_scope")
    return response_path


def _parse_fetch_url(url: str) -> tuple[str, str, int | None, str]:
    """Parse and structurally validate a fetch URL.

    Returns ``(scheme, host, port, path)``. Raises ``ValueError`` whose message
    is a ``RejectionReason`` value on any structural problem.
    """

    if not isinstance(url, str) or not url:
        raise ValueError(RejectionReason.NETWORK_URL_INVALID.value)
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise ValueError(RejectionReason.NETWORK_URL_INVALID.value) from exc
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise ValueError(RejectionReason.NETWORK_SCHEME_UNSUPPORTED.value)
    # Userinfo (``user:pass@host``) is never valid for a governed fetch — it is
    # the classic allowlist-bypass vector. ``parsed.username`` is set when the
    # authority contains ``@``.
    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        raise ValueError(RejectionReason.NETWORK_URL_INVALID.value)
    host = parsed.hostname
    if not host:
        raise ValueError(RejectionReason.NETWORK_URL_INVALID.value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(RejectionReason.NETWORK_URL_INVALID.value) from exc
    return parsed.scheme, host.lower(), port, parsed.path or "/"


def _effective_port(scheme: str, port: int | None) -> int:
    """The port a URL targets, filling in the scheme default when unstated."""

    if port is not None:
        return port
    return 443 if scheme == "https" else 80


def _url_in_allowlist(
    scheme: str, host: str, port: int | None, path: str, network_allow: tuple[str, ...]
) -> bool:
    """Structural allowlist match: exact scheme + host + effective port, path prefix.

    Ports are compared by *effective* value (scheme default filled in), so a
    port-less allowlist entry (``http://host/``) authorizes only the default
    port — never an arbitrary internal-service port like ``:6379`` on the same
    host. A non-default port must be named in the allowlist explicitly.
    """

    target_port = _effective_port(scheme, port)
    for prefix in network_allow:
        p = urlsplit(prefix)
        if p.scheme != scheme:
            continue
        if (p.hostname or "").lower() != host:
            continue
        if _effective_port(p.scheme, p.port) != target_port:
            continue
        if path.startswith(p.path or "/"):
            return True
    return False


def _resolves_to_private(host: str, port: int | None) -> bool:
    """True if the host resolves to (or is) a private/loopback/link-local address.

    Unresolvable hosts are treated as unsafe (return True) so the caller rejects.
    """

    try:
        ip = ipaddress.ip_address(host)
        candidates = [ip]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, port or 0, type=socket.SOCK_STREAM)
        except socket.gaierror:
            return True
        candidates = [ipaddress.ip_address(info[4][0]) for info in infos]
    for ip in candidates:
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return True
    return False


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse to follow redirects: a 3xx re-introduces SSRF past the allowlist."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        raise urllib.error.HTTPError(
            req.full_url, code, "redirect_not_allowed", headers, fp
        )


class NetworkFetchAdapter:
    """Local governed network.fetch adapter (outbound HTTP(S) GET)."""

    adapter = "network"
    operation = "fetch"
    capability = "network.fetch"

    def prepare(
        self,
        scope: Scope,
        proposal: Proposal,
        intent: Intent,
        trace: Trace,
    ) -> AdapterPreparation | EffectResult:
        """Validate a network-fetch intent and build dry-run evidence."""

        url = intent.input.get("url")
        try:
            scheme, host, port, path = _parse_fetch_url(url)
        except ValueError as exc:
            return reject(trace, scope, intent.intent_id, RejectionReason(str(exc)))

        method = intent.input.get("method", "GET")
        if method not in ALLOWED_METHODS:
            return reject(
                trace,
                scope,
                intent.intent_id,
                RejectionReason.NETWORK_METHOD_NOT_ALLOWED,
                method=str(method),
            )

        if not scope.network_allow or not _url_in_allowlist(
            scheme, host, port, path, scope.network_allow
        ):
            return reject(
                trace,
                scope,
                intent.intent_id,
                RejectionReason.NETWORK_URL_NOT_IN_ALLOWLIST,
                host=host,
            )

        if not scope.allow_private_network and _resolves_to_private(host, port):
            return reject(
                trace,
                scope,
                intent.intent_id,
                RejectionReason.NETWORK_HOST_IS_PRIVATE,
                host=host,
            )

        try:
            response_path = _network_store_path(scope, intent.target)
        except ValueError as exc:
            return reject(trace, scope, intent.intent_id, RejectionReason(str(exc)))

        return AdapterPreparation(
            effect_kind=self.capability,
            commit_target=str(url),
            checks=[
                "capability:network.fetch",
                "scheme_allowed",
                "url_in_allowlist",
                "host_not_private",
                "target_path_safe",
            ],
            dry_run_summary=f"GET {url} -> {response_path}",
            dry_run_fields={
                "url_sha256": sha256_bytes(str(url).encode("utf-8")),
                "host": host,
                "method": method,
            },
            payload={
                "url": str(url),
                "host": host,
                "port": port,
                "response_path": response_path,
            },
        )

    def commit(
        self,
        scope: Scope,
        proposal: Proposal,
        intent: Intent,
        trace: Trace,
        preparation: AdapterPreparation,
    ) -> CommitEvidence | EffectResult:
        """Fetch the URL under guards, persist the body, and verify read-back."""

        url = preparation.payload["url"]
        host = preparation.payload["host"]
        port = preparation.payload["port"]
        response_path = preparation.payload["response_path"]

        # Re-check resolution immediately before connecting to narrow the
        # DNS-rebinding window (full IP pinning is a documented future item).
        if not scope.allow_private_network and _resolves_to_private(host, port):
            return reject(
                trace,
                scope,
                intent.intent_id,
                RejectionReason.NETWORK_HOST_IS_PRIVATE,
                host=host,
            )

        request = urllib.request.Request(
            url,
            method="GET",
            headers={"User-Agent": _USER_AGENT, "Accept-Encoding": "identity"},
        )
        opener = urllib.request.build_opener(_NoRedirectHandler)
        try:
            with opener.open(request, timeout=READ_TIMEOUT_SECONDS) as response:
                declared = response.headers.get("Content-Length")
                if declared is not None and declared.isdigit():
                    if int(declared) > scope.max_bytes:
                        raise ValueError(
                            RejectionReason.NETWORK_RESPONSE_TOO_LARGE.value
                        )
                status_code = response.status
                body = b""
                while True:
                    chunk = response.read(4096)
                    if not chunk:
                        break
                    body += chunk
                    if len(body) > scope.max_bytes:
                        raise ValueError(
                            RejectionReason.NETWORK_RESPONSE_TOO_LARGE.value
                        )
        except urllib.error.HTTPError as exc:
            reason = (
                RejectionReason.NETWORK_REDIRECT_NOT_ALLOWED
                if 300 <= exc.code < 400
                else RejectionReason.NETWORK_REQUEST_FAILED
            )
            trace.add(
                "adapter.commit.failed",
                error_type="HTTPError",
                status=exc.code,
                target=str(url),
            )
            return reject(
                trace, scope, intent.intent_id, reason, status=exc.code
            )
        except ValueError as exc:
            return reject(
                trace,
                scope,
                intent.intent_id,
                RejectionReason(str(exc)),
            )
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            trace.add(
                "adapter.commit.failed",
                error_type=exc.__class__.__name__,
                target=str(url),
            )
            return reject(
                trace,
                scope,
                intent.intent_id,
                RejectionReason.NETWORK_REQUEST_FAILED,
                error_type=exc.__class__.__name__,
            )

        body_hash = sha256_bytes(body)

        def _verify_readback(readback: bytes) -> None:
            if sha256_bytes(readback) != body_hash:
                raise ValueError("response_read_back_mismatch")

        try:
            anchored_atomic_write(scope, response_path, body, verify=_verify_readback)
        except (OSError, ValueError) as exc:
            trace.add(
                "adapter.persist.failed",
                error_type=exc.__class__.__name__,
                target=str(response_path),
            )
            return reject(
                trace,
                scope,
                intent.intent_id,
                RejectionReason.ADAPTER_COMMIT_FAILED,
                target=str(response_path),
            )

        ack = {
            "adapter": "network",
            "target": str(response_path),
            "handle": str(response_path),
            "url": url,
            "status_code": status_code,
            "sha256": body_hash,
            "bytes": len(body),
        }
        verification = {
            "status": "verified",
            "method": "response_body_read_back_sha256",
            "detail": {
                "sha256": body_hash,
                "bytes": len(body),
                "status_code": status_code,
            },
        }
        return CommitEvidence(
            acknowledgement=ack,
            verification=verification,
            committed_at=now_timestamp(),
        )


def evaluate_network_fetch(
    scope: Scope,
    proposal: Proposal,
    *,
    approval_granted: bool = False,
    approval: ApprovalDecision | None = None,
    _stop_at_approval: bool = False,
) -> tuple[EffectResult, Trace]:
    """Evaluate one governed network-fetch proposal end to end.

    When ``_stop_at_approval`` is True the evaluator runs admission, allowlist,
    and approval phases and stops before any network call — no request is issued
    and no file is written. Used by ``interpret``.
    """

    return evaluate_with_adapter(
        scope,
        proposal,
        NetworkFetchAdapter(),
        approval_granted=approval_granted,
        approval=approval,
        _stop_at_approval=_stop_at_approval,
    )


def sample_network_scope(
    root: Path,
    *,
    allow_prefix: str,
    approval_required: bool = True,
    allow_private_network: bool = False,
) -> Scope:
    """Build a sample network-fetch scope for one allowlisted URL prefix."""

    return Scope(
        scope_id="local_network_sandbox",
        sandbox_root=root.resolve(),
        capabilities=frozenset({"network.fetch"}),
        approval_required_for=(
            frozenset({"network.fetch"}) if approval_required else frozenset()
        ),
        network_allow=(allow_prefix,),
        allow_private_network=allow_private_network,
    )


def sample_network_proposal(
    url: str,
    *,
    target: str = "responses/fetch.bin",
) -> Proposal:
    """Build a sample network-fetch proposal."""

    proposal_id = "prop_network_fetch_001"
    return Proposal(
        proposal_id=proposal_id,
        actor="agent:hermes",
        speech_act="intend",
        reason="fetch an allowlisted resource under governance",
        confidence=0.8,
        evidence=["scope:local_network_sandbox"],
        intent=Intent(
            intent_id="intent_network_fetch_001",
            proposal_id=proposal_id,
            adapter="network",
            operation="fetch",
            target=target,
            input={"url": url, "method": "GET"},
            required_capability="network.fetch",
        ),
    )
