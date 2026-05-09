"""Governed local file.write adapter."""

from __future__ import annotations

import os
import stat
import uuid
from pathlib import Path

from fermata.runtime_core import (
    evaluate_with_adapter,
    is_inside,
    normalize_target,
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


def nofollow_directory_flags() -> int:
    """Return flags for opening a directory without following the final symlink."""

    return os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)


def nofollow_file_flags() -> int:
    """Return flags for opening a file without following the final symlink."""

    return os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)


def open_file_parent_fd(scope: Scope, target_path: Path) -> int:
    """Open the target parent directory by walking from the sandbox without links."""

    scope.sandbox_root.mkdir(parents=True, exist_ok=True)
    if scope.sandbox_root.is_symlink():
        raise ValueError(RejectionReason.PATH_COMPONENT_IS_SYMLINK.value)

    resolved_root = scope.sandbox_root.resolve()
    try:
        relative_parts = target_path.parent.relative_to(resolved_root).parts
    except ValueError as exc:
        raise ValueError(RejectionReason.PATH_OUTSIDE_SCOPE.value) from exc

    current_fd = os.open(resolved_root, nofollow_directory_flags())
    try:
        for part in relative_parts:
            try:
                current_stat = os.stat(
                    part,
                    dir_fd=current_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                try:
                    os.mkdir(part, 0o700, dir_fd=current_fd)
                except FileExistsError:
                    pass
                except OSError as mkdir_exc:
                    raise ValueError(
                        RejectionReason.ADAPTER_COMMIT_FAILED.value
                    ) from mkdir_exc
                try:
                    current_stat = os.stat(
                        part,
                        dir_fd=current_fd,
                        follow_symlinks=False,
                    )
                except OSError as stat_exc:
                    raise ValueError(
                        RejectionReason.ADAPTER_COMMIT_FAILED.value
                    ) from stat_exc
            if stat.S_ISLNK(current_stat.st_mode):
                raise ValueError(RejectionReason.PATH_COMPONENT_IS_SYMLINK.value)
            if not stat.S_ISDIR(current_stat.st_mode):
                raise ValueError(RejectionReason.ADAPTER_COMMIT_FAILED.value)

            next_fd = os.open(part, nofollow_directory_flags(), dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
    except BaseException:
        os.close(current_fd)
        raise
    return current_fd


def target_rejection_for_existing_path(
    parent_fd: int,
    target_name: str,
    *,
    overwrite_requested: bool,
) -> RejectionReason | None:
    """Return the governed rejection for an existing target, if any."""

    try:
        target_stat = os.stat(
            target_name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return None

    if stat.S_ISLNK(target_stat.st_mode):
        return RejectionReason.TARGET_IS_SYMLINK
    if stat.S_ISDIR(target_stat.st_mode):
        return RejectionReason.TARGET_IS_DIRECTORY
    if not overwrite_requested:
        return RejectionReason.TARGET_EXISTS_NO_OVERWRITE
    return None


def commit_error_result(
    trace: Trace,
    scope: Scope,
    intent: Intent,
    exc: OSError | ValueError,
    *,
    target: str,
) -> EffectResult:
    """Map an adapter commit exception to a governed rejection result."""

    reason_text = str(exc)
    if reason_text in RejectionReason._value2member_map_:
        reason = RejectionReason(reason_text)
        if reason == RejectionReason.ADAPTER_COMMIT_FAILED:
            trace.add(
                "adapter.commit.failed",
                error_type=exc.__class__.__name__,
                target=target,
            )
        return reject(
            trace,
            scope,
            intent.intent_id,
            reason,
            target=target,
        )
    trace.add(
        "adapter.commit.failed",
        error_type=exc.__class__.__name__,
        target=target,
    )
    return reject(
        trace,
        scope,
        intent.intent_id,
        RejectionReason.ADAPTER_COMMIT_FAILED,
        error_type=exc.__class__.__name__,
    )


class FileWriteAdapter:
    """Local governed file.write adapter."""

    adapter = "file"
    operation = "write"
    capability = "file.write"

    def prepare(
        self,
        scope: Scope,
        proposal: Proposal,
        intent: Intent,
        trace: Trace,
    ) -> AdapterPreparation | EffectResult:
        """Validate file-write intent and build dry-run evidence."""

        target_path = normalize_target(scope, intent.target)
        if not is_inside(scope.sandbox_root, target_path):
            return reject(
                trace,
                scope,
                intent.intent_id,
                RejectionReason.PATH_OUTSIDE_SCOPE,
                target=str(target_path),
                sandbox_root=str(scope.sandbox_root),
            )

        raw_target = Path(intent.target)
        candidate_path = (
            raw_target if raw_target.is_absolute() else scope.sandbox_root / raw_target
        )
        sandbox_root_resolved = scope.sandbox_root.resolve()
        walker = candidate_path
        visited: set[Path] = set()
        while walker not in visited:
            visited.add(walker)
            if walker.is_symlink():
                reason = (
                    "target_is_symlink"
                    if walker == candidate_path
                    else "path_component_is_symlink"
                )
                return reject(
                    trace,
                    scope,
                    intent.intent_id,
                    RejectionReason(reason),
                    symlink_path=str(walker),
                )
            if walker == walker.parent:
                break
            walker = walker.parent
            try:
                if walker.resolve() == sandbox_root_resolved:
                    break
            except OSError:
                break

        content = intent.input.get("content")
        if not isinstance(content, str):
            return reject(
                trace,
                scope,
                intent.intent_id,
                RejectionReason.CONTENT_MISSING_OR_NOT_STRING,
            )

        content_bytes = content.encode("utf-8")
        if len(content_bytes) > scope.max_bytes:
            return reject(
                trace,
                scope,
                intent.intent_id,
                RejectionReason.INPUT_TOO_LARGE,
                bytes=len(content_bytes),
                max_bytes=scope.max_bytes,
            )

        if target_path.exists() and target_path.is_dir():
            return reject(
                trace,
                scope,
                intent.intent_id,
                RejectionReason.TARGET_IS_DIRECTORY,
                target=str(target_path),
            )

        overwrite_requested = bool(intent.input.get("overwrite"))
        if (
            target_path.exists()
            and not target_path.is_dir()
            and not overwrite_requested
        ):
            return reject(
                trace,
                scope,
                intent.intent_id,
                RejectionReason.TARGET_EXISTS_NO_OVERWRITE,
                target=str(target_path),
            )

        input_hash = sha256_bytes(content_bytes)
        return AdapterPreparation(
            effect_kind=self.capability,
            commit_target=str(target_path),
            checks=["capability:file.write", "inside_scope", "bytes_under_limit"],
            dry_run_summary=f"Write {len(content_bytes)} bytes to {target_path}",
            dry_run_fields={"input_sha256": input_hash},
            payload={
                "target_path": target_path,
                "content_bytes": content_bytes,
                "input_hash": input_hash,
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
        """Commit a prepared file write and verify the target bytes."""

        target_path = preparation.payload["target_path"]
        content_bytes = preparation.payload["content_bytes"]
        input_hash = preparation.payload["input_hash"]
        overwrite_requested = bool(intent.input.get("overwrite"))
        parent_fd: int | None = None
        temp_name = f".{target_path.name}.{uuid.uuid4().hex}.tmp"
        temp_created = False
        try:
            parent_fd = open_file_parent_fd(scope, target_path)
            existing_rejection = target_rejection_for_existing_path(
                parent_fd,
                target_path.name,
                overwrite_requested=overwrite_requested,
            )
            if existing_rejection is not None:
                os.close(parent_fd)
                parent_fd = None
                return reject(
                    trace,
                    scope,
                    intent.intent_id,
                    existing_rejection,
                    target=str(target_path),
                )

            fd = os.open(
                temp_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=parent_fd,
            )
            temp_created = True
            with os.fdopen(fd, "wb") as temp_file:
                os.fchmod(temp_file.fileno(), 0o600)
                temp_file.write(content_bytes)
                temp_file.flush()
                os.fsync(temp_file.fileno())

            temp_read_fd = os.open(
                temp_name,
                nofollow_file_flags(),
                dir_fd=parent_fd,
            )
            with os.fdopen(temp_read_fd, "rb") as temp_file:
                readback = temp_file.read()
            output_hash = sha256_bytes(readback)
            if output_hash != input_hash:
                raise ValueError("read_back_hash_mismatch")

            if overwrite_requested:
                os.rename(
                    temp_name,
                    target_path.name,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                )
                temp_created = False
            else:
                try:
                    os.link(
                        temp_name,
                        target_path.name,
                        src_dir_fd=parent_fd,
                        dst_dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                except FileExistsError as exc:
                    late_rejection = target_rejection_for_existing_path(
                        parent_fd,
                        target_path.name,
                        overwrite_requested=overwrite_requested,
                    )
                    if late_rejection is not None:
                        raise ValueError(late_rejection.value) from exc
                    raise
                os.unlink(temp_name, dir_fd=parent_fd)
                temp_created = False
        except (OSError, ValueError) as exc:
            if temp_created and parent_fd is not None:
                try:
                    os.unlink(temp_name, dir_fd=parent_fd)
                except OSError:
                    trace.add("adapter.temp_cleanup.failed", target=temp_name)
            if parent_fd is not None:
                os.close(parent_fd)
                parent_fd = None
            return commit_error_result(
                trace,
                scope,
                intent,
                exc,
                target=str(target_path),
            )

        if parent_fd is not None:
            try:
                os.fsync(parent_fd)
            except OSError:
                pass

        try:
            if parent_fd is None:
                raise OSError("parent_fd_missing")
            final_fd = os.open(
                target_path.name,
                nofollow_file_flags(),
                dir_fd=parent_fd,
            )
            with os.fdopen(final_fd, "rb") as final_file:
                final_bytes = final_file.read()
        except OSError as exc:
            trace.add(
                "verification.failed",
                error_type=exc.__class__.__name__,
                target=str(target_path),
            )
            return reject(
                trace,
                scope,
                intent.intent_id,
                RejectionReason.VERIFICATION_READ_FAILED,
                error_type=exc.__class__.__name__,
            )
        finally:
            if parent_fd is not None:
                os.close(parent_fd)

        final_hash = sha256_bytes(final_bytes)
        if final_hash != input_hash:
            trace.add(
                "verification.failed",
                target=str(target_path),
                input_sha256=input_hash,
                target_sha256=final_hash,
            )
            return reject(
                trace,
                scope,
                intent.intent_id,
                RejectionReason.VERIFICATION_FAILED_POST_COMMIT,
                input_sha256=input_hash,
                target_sha256=final_hash,
            )

        ack = {
            "adapter": "file",
            "target": str(target_path),
            "handle": str(target_path),
            "sha256": final_hash,
            "bytes": len(final_bytes),
        }
        verification = {
            "status": "verified",
            "method": "post_rename_read_back_sha256",
            "detail": {"sha256": final_hash, "bytes": len(final_bytes)},
        }
        return CommitEvidence(
            acknowledgement=ack,
            verification=verification,
            committed_at=now_timestamp(),
        )


def evaluate_file_write(
    scope: Scope,
    proposal: Proposal,
    *,
    approval_granted: bool = False,
    approval: ApprovalDecision | None = None,
    _stop_at_approval: bool = False,
) -> tuple[EffectResult, Trace]:
    """Evaluate one governed file-write proposal end to end.

    When ``_stop_at_approval`` is True, the evaluator runs pure admission,
    verification, and approval phases and stops before any adapter commit —
    returning an ``EffectState.APPROVED`` result whose trace ends at
    ``approval.granted``. The filesystem is never touched. Used by
    ``interpret`` to expose the state-machine spine without world effects.
    """

    return evaluate_with_adapter(
        scope,
        proposal,
        FileWriteAdapter(),
        approval_granted=approval_granted,
        approval=approval,
        _stop_at_approval=_stop_at_approval,
    )

def sample_proposal(target: str = "charter-note.txt") -> Proposal:
    """Build the canonical sample file-write proposal."""

    proposal_id = "prop_file_write_001"
    return Proposal(
        proposal_id=proposal_id,
        actor="agent:hermes",
        speech_act="intend",
        reason="record the charter chorus for the next kata",
        confidence=0.82,
        evidence=["user:proceed", "scope:charter_note_sandbox"],
        intent=Intent(
            intent_id="intent_file_write_001",
            proposal_id=proposal_id,
            adapter="file",
            operation="write",
            target=target,
            input={
                "content": "Agents may propose; only governed effects may commit.\n"
            },
            required_capability="file.write",
        ),
    )


def sample_scope(root: Path, *, approval_required: bool = True) -> Scope:
    """Build the canonical sample performer-governed scope."""

    return Scope(
        scope_id="charter_note_sandbox",
        sandbox_root=root.resolve(),
        capabilities=frozenset({"file.read", "file.write"}),
        approval_required_for=(
            frozenset({"file.write"}) if approval_required else frozenset()
        ),
    )
