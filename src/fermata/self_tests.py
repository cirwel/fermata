"""Acceptance self-tests for the local governed-effect adapters."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fermata.file_adapter import (
    FileWriteAdapter,
    evaluate_file_write,
    sample_proposal,
    sample_scope,
)
from fermata.interpreter import interpret
from fermata.memory_adapter import (
    evaluate_memory_write,
    memory_store_path,
    sample_memory_proposal,
    sample_memory_scope,
)
from fermata.runtime_core import append_trace_ledger, trace_ledger_path
from fermata.runtime_ir import (
    AdapterPreparation,
    ApprovalAuthority,
    ApprovalDecision,
    ApprovalStatus,
    EffectResult,
    EffectState,
    Intent,
    Proposal,
    Scope,
    Trace,
    approval_for,
    intent_sha256,
    make_approval_decision,
    now_timestamp,
)


def run_self_tests() -> dict[str, Any]:
    """Run acceptance checks for the file-write adapter."""

    results: dict[str, Any] = {}

    with tempfile.TemporaryDirectory(prefix="governed_effect_") as tmp:
        root = Path(tmp) / "sandbox"

        non_intent, non_intent_trace = evaluate_file_write(
            sample_scope(root, approval_required=False),
            Proposal(
                proposal_id="prop_claim_001",
                actor="agent:hermes",
                speech_act="claim",
                reason="not an effect intent",
                confidence=0.7,
                evidence=[],
            ),
            approval_granted=True,
        )
        assert non_intent.state == EffectState.REJECTED
        assert non_intent.intent_id is None
        assert non_intent.rejection_reason == "proposal_is_not_an_intent"
        assert "adapter.commit.started" not in [
            event["type"] for event in non_intent_trace.events
        ]
        results["non_intent_rejected"] = non_intent.to_record()
        results["non_intent_trace"] = non_intent_trace.to_record()

        bad_content_proposal = Proposal(
            proposal_id="prop_bad_content_001",
            actor="agent:hermes",
            speech_act="intend",
            reason="malformed content should not reach the adapter",
            confidence=0.71,
            evidence=[],
            intent=Intent(
                intent_id="intent_bad_content_001",
                proposal_id="prop_bad_content_001",
                adapter="file",
                operation="write",
                target="bad-content.txt",
                input={},
                required_capability="file.write",
            ),
        )
        bad_content, bad_content_trace = evaluate_file_write(
            sample_scope(root, approval_required=False),
            bad_content_proposal,
            approval_granted=True,
        )
        assert bad_content.state == EffectState.REJECTED
        assert bad_content.rejection_reason == "content_missing_or_not_string"
        assert "adapter.commit.started" not in [
            event["type"] for event in bad_content_trace.events
        ]
        results["content_missing_rejected"] = bad_content.to_record()
        results["content_missing_trace"] = bad_content_trace.to_record()

        directory_target = root / "already-a-directory"
        directory_target.mkdir(parents=True)
        directory_result, directory_trace = evaluate_file_write(
            sample_scope(root, approval_required=False),
            sample_proposal("already-a-directory"),
            approval_granted=True,
        )
        assert directory_result.state == EffectState.REJECTED
        assert directory_result.rejection_reason == "target_is_directory"
        assert "adapter.commit.started" not in [
            event["type"] for event in directory_trace.events
        ]
        assert not list(root.glob(".already-a-directory.*.tmp"))
        results["directory_target_rejected"] = directory_result.to_record()
        results["directory_target_trace"] = directory_trace.to_record()

        blocked_parent = root / "blocked-parent"
        blocked_parent.write_text("not a directory")
        adapter_error, adapter_error_trace = evaluate_file_write(
            sample_scope(root, approval_required=False),
            sample_proposal("blocked-parent/file.txt"),
            approval_granted=True,
        )
        assert adapter_error.state == EffectState.REJECTED
        assert adapter_error.rejection_reason == "adapter_commit_failed"
        adapter_error_events = [event["type"] for event in adapter_error_trace.events]
        assert "adapter.commit.started" in adapter_error_events
        assert "adapter.commit.failed" in adapter_error_events
        results["adapter_error_rejected"] = adapter_error.to_record()
        results["adapter_error_trace"] = adapter_error_trace.to_record()

        allowed_write_scope = sample_scope(root, approval_required=True)
        allowed_write_proposal = sample_proposal()
        assert allowed_write_proposal.intent is not None
        allowed_write_approval = make_approval_decision(
            allowed_write_scope,
            allowed_write_proposal.intent,
            approver="performer:steward",
            reason="steward_authorized",
        )
        committed, committed_trace = evaluate_file_write(
            allowed_write_scope,
            allowed_write_proposal,
            approval=allowed_write_approval,
        )
        assert committed.state == EffectState.COMMITTED
        assert committed.acknowledgement is not None
        assert committed.approval is not None
        assert committed.approval["approver"] == "performer:steward"
        assert committed.approval["reason"] == "steward_authorized"
        target = Path(committed.acknowledgement["target"])
        assert target.exists()
        assert committed.verification is not None
        assert committed.verification["status"] == "verified"
        assert committed.committed_at is not None
        results["allowed_write_commits"] = committed.to_record()
        results["allowed_write_trace"] = committed_trace.to_record()
        results["allowed_write_trace_events"] = [
            event["type"] for event in committed_trace.events
        ]

        trace_ledger_evidence = append_trace_ledger(
            sample_scope(root, approval_required=False),
            committed_trace,
        )
        assert trace_ledger_evidence["acknowledgement"]["trace_id"] == (
            committed_trace.trace_id
        )
        assert trace_ledger_evidence["verification"]["status"] == "verified"
        assert trace_ledger_path(
            sample_scope(root, approval_required=False)
        ).read_text(encoding="utf-8").count(committed_trace.trace_id) == 1
        results["trace_ledger_append_verified"] = trace_ledger_evidence

        old_umask = os.umask(0o444)
        try:
            restrictive_file, restrictive_file_trace = evaluate_file_write(
                sample_scope(root, approval_required=False),
                sample_proposal("restrictive-umask-file.txt"),
                approval_granted=True,
            )
        finally:
            os.umask(old_umask)
        assert restrictive_file.state == EffectState.COMMITTED
        restrictive_file_target = Path(restrictive_file.acknowledgement["target"])
        assert restrictive_file_target.read_text(encoding="utf-8") == (
            "Agents may propose; only governed effects may commit.\n"
        )
        assert "adapter.commit.failed" not in [
            event["type"] for event in restrictive_file_trace.events
        ]
        results["restrictive_umask_file_write_commits_verified"] = (
            restrictive_file.to_record()
        )
        results["restrictive_umask_file_write_trace"] = (
            restrictive_file_trace.to_record()
        )

        escaped, escaped_trace = evaluate_file_write(
            sample_scope(root, approval_required=False),
            sample_proposal("../outside-scope.txt"),
            approval_granted=True,
        )
        assert escaped.state == EffectState.REJECTED
        assert escaped.rejection_reason == "path_outside_scope"
        assert "adapter.commit.started" not in [
            event["type"] for event in escaped_trace.events
        ]
        results["path_escape_rejected"] = escaped.to_record()
        results["path_escape_trace"] = escaped_trace.to_record()

        no_cap_scope = Scope(
            scope_id="no_write_scope",
            sandbox_root=root.resolve(),
            capabilities=frozenset({"file.read"}),
            approval_required_for=frozenset(),
        )
        no_cap, no_cap_trace = evaluate_file_write(
            no_cap_scope,
            sample_proposal(),
            approval_granted=True,
        )
        assert no_cap.state == EffectState.REJECTED
        assert no_cap.rejection_reason == "missing_capability"
        assert "adapter.commit.started" not in [
            event["type"] for event in no_cap_trace.events
        ]
        results["missing_capability_rejected"] = no_cap.to_record()
        results["missing_capability_trace"] = no_cap_trace.to_record()

        spoofed_file_proposal = Proposal(
            proposal_id="prop_file_spoof_001",
            actor="agent:hermes",
            speech_act="intend",
            reason="adapter operation should derive its own capability",
            confidence=0.68,
            evidence=[],
            intent=Intent(
                intent_id="intent_file_spoof_001",
                proposal_id="prop_file_spoof_001",
                adapter="file",
                operation="write",
                target="spoofed-capability.txt",
                input={"content": "should not commit\n"},
                required_capability="memory.write",
            ),
        )
        spoofed_file, spoofed_file_trace = evaluate_file_write(
            Scope(
                scope_id="memory_only_scope",
                sandbox_root=root.resolve(),
                capabilities=frozenset({"memory.write"}),
                approval_required_for=frozenset(),
            ),
            spoofed_file_proposal,
            approval_granted=True,
        )
        assert spoofed_file.state == EffectState.REJECTED
        assert spoofed_file.rejection_reason == "unsupported_capability_for_operation"
        assert "adapter.commit.started" not in [
            event["type"] for event in spoofed_file_trace.events
        ]
        assert not (root / "spoofed-capability.txt").exists()
        results["capability_spoof_rejected"] = spoofed_file.to_record()
        results["capability_spoof_trace"] = spoofed_file_trace.to_record()

        bad_file_target, bad_file_target_trace = evaluate_file_write(
            sample_scope(root, approval_required=False),
            Proposal(
                proposal_id="prop_file_bad_target_001",
                actor="agent:hermes",
                speech_act="intend",
                reason="malformed target should reject under governance",
                confidence=0.66,
                evidence=[],
                intent=Intent(
                    intent_id="intent_file_bad_target_001",
                    proposal_id="prop_file_bad_target_001",
                    adapter="file",
                    operation="write",
                    target=123,
                    input={"content": "should not commit\n"},
                    required_capability="file.write",
                ),
            ),
            approval_granted=True,
        )
        assert bad_file_target.state == EffectState.REJECTED
        assert bad_file_target.rejection_reason == "target_missing_or_not_string"
        assert "adapter.commit.started" not in [
            event["type"] for event in bad_file_target_trace.events
        ]
        results["target_not_string_rejected"] = bad_file_target.to_record()
        results["target_not_string_trace"] = bad_file_target_trace.to_record()

        bad_file_input, bad_file_input_trace = evaluate_file_write(
            sample_scope(root, approval_required=False),
            Proposal(
                proposal_id="prop_file_bad_input_001",
                actor="agent:hermes",
                speech_act="intend",
                reason="malformed input should reject under governance",
                confidence=0.65,
                evidence=[],
                intent=Intent(
                    intent_id="intent_file_bad_input_001",
                    proposal_id="prop_file_bad_input_001",
                    adapter="file",
                    operation="write",
                    target="bad-input.txt",
                    input=None,
                    required_capability="file.write",
                ),
            ),
            approval_granted=True,
        )
        assert bad_file_input.state == EffectState.REJECTED
        assert bad_file_input.rejection_reason == "input_missing_or_not_object"
        assert "adapter.commit.started" not in [
            event["type"] for event in bad_file_input_trace.events
        ]
        assert not (root / "bad-input.txt").exists()
        results["input_not_object_rejected"] = bad_file_input.to_record()
        results["input_not_object_trace"] = bad_file_input_trace.to_record()

        paused, paused_trace = evaluate_file_write(
            sample_scope(root, approval_required=True),
            sample_proposal("needs-approval.txt"),
            approval_granted=False,
        )
        assert paused.state == EffectState.PAUSED
        assert paused.required_input == "approval_decision"
        assert "adapter.commit.started" not in [
            event["type"] for event in paused_trace.events
        ]
        assert not (root / "needs-approval.txt").exists()
        results["approval_required_pauses"] = paused.to_record()
        results["approval_required_trace"] = paused_trace.to_record()

        explicit_approval_proposal = sample_proposal("explicit-approval.txt")
        assert explicit_approval_proposal.intent is not None
        explicit_scope = sample_scope(root, approval_required=True)
        explicit_approval = make_approval_decision(
            explicit_scope,
            explicit_approval_proposal.intent,
            approver="performer:steward",
            reason="steward_authorized",
        )
        explicit_committed, explicit_committed_trace = evaluate_file_write(
            explicit_scope,
            explicit_approval_proposal,
            approval=explicit_approval,
        )
        assert explicit_committed.state == EffectState.COMMITTED
        assert explicit_committed.approval is not None
        assert explicit_committed.approval["intent_sha256"] == intent_sha256(
            explicit_approval_proposal.intent
        )
        assert "approval.granted" in [
            event["type"] for event in explicit_committed_trace.events
        ]
        results["explicit_approval_write_commits"] = explicit_committed.to_record()
        results["explicit_approval_write_trace"] = explicit_committed_trace.to_record()

        legacy_approval = approval_for(
            explicit_scope,
            explicit_approval_proposal.intent,
            "file.write",
            approval_granted=True,
        )
        assert legacy_approval.reason == "legacy_boolean_approval_granted"
        assert legacy_approval.approver == "legacy:approval_granted"
        results["legacy_boolean_approval_marked"] = legacy_approval.to_record()

        denied_approval_proposal = sample_proposal("denied-approval.txt")
        assert denied_approval_proposal.intent is not None
        denied_scope = sample_scope(root, approval_required=True)
        denied_approval = make_approval_decision(
            denied_scope,
            denied_approval_proposal.intent,
            status=ApprovalStatus.DENIED,
            approval_id="approval_denied_001",
            approver="performer:steward",
            reason="performer_denied",
        )
        denied_approval_result, denied_approval_trace = evaluate_file_write(
            denied_scope,
            denied_approval_proposal,
            approval=denied_approval,
        )
        assert denied_approval_result.state == EffectState.REJECTED
        assert denied_approval_result.rejection_reason == "approval_denied"
        assert "adapter.commit.started" not in [
            event["type"] for event in denied_approval_trace.events
        ]
        assert not (root / "denied-approval.txt").exists()
        results["approval_denied_rejected"] = denied_approval_result.to_record()
        results["approval_denied_trace"] = denied_approval_trace.to_record()

        mismatched_approval_proposal = sample_proposal("mismatched-approval.txt")
        assert mismatched_approval_proposal.intent is not None
        mismatched_scope = sample_scope(root, approval_required=True)
        mismatched_approval = ApprovalDecision(
            status=ApprovalStatus.APPROVED,
            authority=ApprovalAuthority.PERFORMER,
            approval_id="approval_mismatch_001",
            approver="performer:steward",
            decided_at=now_timestamp(),
            scope_id=mismatched_scope.scope_id,
            intent_id=mismatched_approval_proposal.intent.intent_id,
            intent_sha256="0" * 64,
        )
        mismatched_approval_result, mismatched_approval_trace = evaluate_file_write(
            mismatched_scope,
            mismatched_approval_proposal,
            approval=mismatched_approval,
        )
        assert mismatched_approval_result.state == EffectState.REJECTED
        assert (
            mismatched_approval_result.rejection_reason
            == "approval_intent_hash_mismatch"
        )
        assert "adapter.commit.started" not in [
            event["type"] for event in mismatched_approval_trace.events
        ]
        assert not (root / "mismatched-approval.txt").exists()
        results["approval_intent_hash_mismatch_rejected"] = (
            mismatched_approval_result.to_record()
        )
        results["approval_intent_hash_mismatch_trace"] = (
            mismatched_approval_trace.to_record()
        )

        symlink_target = root / "symlink-at-target.txt"
        symlink_decoy = root / "decoy-target.txt"
        symlink_decoy.write_text("decoy")
        os.symlink(symlink_decoy, symlink_target)
        symlink_at_target, symlink_at_target_trace = evaluate_file_write(
            sample_scope(root, approval_required=False),
            sample_proposal("symlink-at-target.txt"),
            approval_granted=True,
        )
        assert symlink_at_target.state == EffectState.REJECTED
        assert symlink_at_target.rejection_reason == "target_is_symlink"
        assert "adapter.commit.started" not in [
            event["type"] for event in symlink_at_target_trace.events
        ]
        assert symlink_decoy.read_text() == "decoy"
        results["target_is_symlink_rejected"] = symlink_at_target.to_record()
        results["target_is_symlink_trace"] = symlink_at_target_trace.to_record()

        late_target_symlink_proposal = sample_proposal("late-target-symlink.txt")
        assert late_target_symlink_proposal.intent is not None
        late_target_symlink_scope = sample_scope(root, approval_required=False)
        late_target_symlink_trace = Trace(trace_id=f"trace_{uuid.uuid4().hex[:8]}")
        late_target_symlink_preparation = FileWriteAdapter().prepare(
            late_target_symlink_scope,
            late_target_symlink_proposal,
            late_target_symlink_proposal.intent,
            late_target_symlink_trace,
        )
        assert isinstance(late_target_symlink_preparation, AdapterPreparation)
        late_target_decoy = root / "late-target-decoy.txt"
        late_target_decoy.write_text("late decoy")
        os.symlink(late_target_decoy, root / "late-target-symlink.txt")
        late_target_symlink_trace.add(
            "adapter.commit.started",
            adapter="file",
            target=late_target_symlink_preparation.commit_target,
        )
        late_target_symlink = FileWriteAdapter().commit(
            late_target_symlink_scope,
            late_target_symlink_proposal,
            late_target_symlink_proposal.intent,
            late_target_symlink_trace,
            late_target_symlink_preparation,
        )
        assert isinstance(late_target_symlink, EffectResult)
        assert late_target_symlink.state == EffectState.REJECTED
        assert late_target_symlink.rejection_reason == "target_is_symlink"
        assert late_target_decoy.read_text() == "late decoy"
        results["late_target_symlink_rejected"] = late_target_symlink.to_record()
        results["late_target_symlink_trace"] = late_target_symlink_trace.to_record()

        symlink_dir_real = root / "real-subdir"
        symlink_dir_real.mkdir()
        symlink_dir_alias = root / "aliased-subdir"
        os.symlink(symlink_dir_real, symlink_dir_alias)
        path_component_link, path_component_link_trace = evaluate_file_write(
            sample_scope(root, approval_required=False),
            sample_proposal("aliased-subdir/inside.txt"),
            approval_granted=True,
        )
        assert path_component_link.state == EffectState.REJECTED
        assert path_component_link.rejection_reason == "path_component_is_symlink"
        assert "adapter.commit.started" not in [
            event["type"] for event in path_component_link_trace.events
        ]
        assert not (symlink_dir_real / "inside.txt").exists()
        results["path_component_is_symlink_rejected"] = (
            path_component_link.to_record()
        )
        results["path_component_is_symlink_trace"] = (
            path_component_link_trace.to_record()
        )

        late_symlink_parent_proposal = sample_proposal(
            "late-aliased-subdir/inside.txt"
        )
        assert late_symlink_parent_proposal.intent is not None
        late_symlink_parent_scope = sample_scope(root, approval_required=False)
        late_symlink_parent_trace = Trace(trace_id=f"trace_{uuid.uuid4().hex[:8]}")
        late_symlink_parent_preparation = FileWriteAdapter().prepare(
            late_symlink_parent_scope,
            late_symlink_parent_proposal,
            late_symlink_parent_proposal.intent,
            late_symlink_parent_trace,
        )
        assert isinstance(late_symlink_parent_preparation, AdapterPreparation)
        late_symlink_parent_real = root / "late-real-subdir"
        late_symlink_parent_real.mkdir()
        os.symlink(late_symlink_parent_real, root / "late-aliased-subdir")
        late_symlink_parent_trace.add(
            "adapter.commit.started",
            adapter="file",
            target=late_symlink_parent_preparation.commit_target,
        )
        late_symlink_parent = FileWriteAdapter().commit(
            late_symlink_parent_scope,
            late_symlink_parent_proposal,
            late_symlink_parent_proposal.intent,
            late_symlink_parent_trace,
            late_symlink_parent_preparation,
        )
        assert isinstance(late_symlink_parent, EffectResult)
        assert late_symlink_parent.state == EffectState.REJECTED
        assert late_symlink_parent.rejection_reason == "path_component_is_symlink"
        assert not (late_symlink_parent_real / "inside.txt").exists()
        results["late_path_component_is_symlink_rejected"] = (
            late_symlink_parent.to_record()
        )
        results["late_path_component_is_symlink_trace"] = (
            late_symlink_parent_trace.to_record()
        )

        existing_target = root / "existing-target.txt"
        existing_target.write_text("original content\n")
        original_bytes = existing_target.read_bytes()
        no_overwrite, no_overwrite_trace = evaluate_file_write(
            sample_scope(root, approval_required=False),
            sample_proposal("existing-target.txt"),
            approval_granted=True,
        )
        assert no_overwrite.state == EffectState.REJECTED
        assert no_overwrite.rejection_reason == "target_exists_no_overwrite"
        assert "adapter.commit.started" not in [
            event["type"] for event in no_overwrite_trace.events
        ]
        assert existing_target.read_bytes() == original_bytes
        results["target_exists_no_overwrite_rejected"] = no_overwrite.to_record()
        results["target_exists_no_overwrite_trace"] = no_overwrite_trace.to_record()

        late_existing_proposal = sample_proposal("late-existing-target.txt")
        assert late_existing_proposal.intent is not None
        late_existing_scope = sample_scope(root, approval_required=False)
        late_existing_trace = Trace(trace_id=f"trace_{uuid.uuid4().hex[:8]}")
        late_existing_preparation = FileWriteAdapter().prepare(
            late_existing_scope,
            late_existing_proposal,
            late_existing_proposal.intent,
            late_existing_trace,
        )
        assert isinstance(late_existing_preparation, AdapterPreparation)
        late_existing_target = root / "late-existing-target.txt"
        late_existing_target.write_text("raced content\n")
        late_existing_trace.add(
            "adapter.commit.started",
            adapter="file",
            target=late_existing_preparation.commit_target,
        )
        late_existing = FileWriteAdapter().commit(
            late_existing_scope,
            late_existing_proposal,
            late_existing_proposal.intent,
            late_existing_trace,
            late_existing_preparation,
        )
        assert isinstance(late_existing, EffectResult)
        assert late_existing.state == EffectState.REJECTED
        assert late_existing.rejection_reason == "target_exists_no_overwrite"
        assert late_existing_target.read_text() == "raced content\n"
        results["late_target_exists_no_overwrite_rejected"] = (
            late_existing.to_record()
        )
        results["late_target_exists_no_overwrite_trace"] = (
            late_existing_trace.to_record()
        )

        overwrite_proposal = sample_proposal("existing-target.txt")
        assert overwrite_proposal.intent is not None
        overwrite_proposal = Proposal(
            proposal_id=overwrite_proposal.proposal_id,
            actor=overwrite_proposal.actor,
            speech_act=overwrite_proposal.speech_act,
            reason=overwrite_proposal.reason,
            confidence=overwrite_proposal.confidence,
            evidence=overwrite_proposal.evidence,
            intent=Intent(
                intent_id=overwrite_proposal.intent.intent_id,
                proposal_id=overwrite_proposal.intent.proposal_id,
                adapter=overwrite_proposal.intent.adapter,
                operation=overwrite_proposal.intent.operation,
                target=overwrite_proposal.intent.target,
                input={**overwrite_proposal.intent.input, "overwrite": True},
                required_capability=overwrite_proposal.intent.required_capability,
            ),
        )
        overwrote, overwrote_trace = evaluate_file_write(
            sample_scope(root, approval_required=False),
            overwrite_proposal,
            approval_granted=True,
        )
        assert overwrote.state == EffectState.COMMITTED
        assert overwrote.acknowledgement is not None
        assert existing_target.read_text(encoding="utf-8") == (
            "Agents may propose; only governed effects may commit.\n"
        )
        assert "effect.committed" in [
            event["type"] for event in overwrote_trace.events
        ]
        results["target_exists_with_overwrite_commits"] = overwrote.to_record()
        results["target_exists_with_overwrite_trace"] = overwrote_trace.to_record()

        allowed_memory_scope = sample_memory_scope(root, approval_required=True)
        allowed_memory_proposal = sample_memory_proposal()
        assert allowed_memory_proposal.intent is not None
        allowed_memory_approval = make_approval_decision(
            allowed_memory_scope,
            allowed_memory_proposal.intent,
            approver="performer:steward",
            reason="steward_authorized",
        )
        memory_committed, memory_committed_trace = evaluate_memory_write(
            allowed_memory_scope,
            allowed_memory_proposal,
            approval=allowed_memory_approval,
        )
        assert memory_committed.state == EffectState.COMMITTED
        assert memory_committed.acknowledgement is not None
        assert memory_committed.approval is not None
        assert memory_committed.approval["approver"] == "performer:steward"
        assert memory_committed.approval["reason"] == "steward_authorized"
        assert memory_committed.acknowledgement["adapter"] == "memory"
        assert memory_committed.acknowledgement["record_id"]
        assert memory_committed.acknowledgement["version"] == 1
        assert memory_committed.verification is not None
        assert memory_committed.verification["status"] == "verified"
        memory_store = Path(memory_committed.acknowledgement["store"])
        assert memory_store.exists()
        assert memory_committed.acknowledgement["record_id"] in memory_store.read_text()
        results["allowed_memory_write_commits"] = memory_committed.to_record()
        results["allowed_memory_write_trace"] = memory_committed_trace.to_record()
        results["allowed_memory_write_trace_events"] = [
            event["type"] for event in memory_committed_trace.events
        ]

        bad_memory_proposal = sample_memory_proposal()
        assert bad_memory_proposal.intent is not None
        bad_memory_proposal = Proposal(
            proposal_id="prop_bad_memory_001",
            actor=bad_memory_proposal.actor,
            speech_act="intend",
            reason="malformed memory content should not reach the adapter",
            confidence=0.72,
            evidence=bad_memory_proposal.evidence,
            intent=Intent(
                intent_id="intent_bad_memory_001",
                proposal_id="prop_bad_memory_001",
                adapter="memory",
                operation="write",
                target="project/bad-memory",
                input={},
                required_capability="memory.write",
            ),
        )
        bad_memory, bad_memory_trace = evaluate_memory_write(
            sample_memory_scope(root, approval_required=False),
            bad_memory_proposal,
            approval_granted=True,
        )
        assert bad_memory.state == EffectState.REJECTED
        assert bad_memory.rejection_reason == "memory_content_missing_or_not_string"
        assert "adapter.commit.started" not in [
            event["type"] for event in bad_memory_trace.events
        ]
        results["memory_content_missing_rejected"] = bad_memory.to_record()
        results["memory_content_missing_trace"] = bad_memory_trace.to_record()

        no_memory_cap_scope = Scope(
            scope_id="no_memory_write_scope",
            sandbox_root=root.resolve(),
            capabilities=frozenset({"memory.read"}),
            approval_required_for=frozenset(),
        )
        no_memory_cap, no_memory_cap_trace = evaluate_memory_write(
            no_memory_cap_scope,
            sample_memory_proposal("project/no-capability"),
            approval_granted=True,
        )
        assert no_memory_cap.state == EffectState.REJECTED
        assert no_memory_cap.rejection_reason == "missing_capability"
        assert "adapter.commit.started" not in [
            event["type"] for event in no_memory_cap_trace.events
        ]
        results["memory_missing_capability_rejected"] = no_memory_cap.to_record()
        results["memory_missing_capability_trace"] = no_memory_cap_trace.to_record()

        spoofed_memory_proposal = Proposal(
            proposal_id="prop_memory_spoof_001",
            actor="agent:hermes",
            speech_act="intend",
            reason=(
                "memory writes must require memory.write regardless of proposal text"
            ),
            confidence=0.69,
            evidence=[],
            intent=Intent(
                intent_id="intent_memory_spoof_001",
                proposal_id="prop_memory_spoof_001",
                adapter="memory",
                operation="write",
                target="project/spoofed-capability",
                input={
                    "content": "should not commit\n",
                    "provenance": ["test:capability-spoof"],
                },
                required_capability="file.write",
            ),
        )
        spoofed_memory, spoofed_memory_trace = evaluate_memory_write(
            Scope(
                scope_id="file_only_scope",
                sandbox_root=root.resolve(),
                capabilities=frozenset({"file.write"}),
                approval_required_for=frozenset(),
            ),
            spoofed_memory_proposal,
            approval_granted=True,
        )
        assert spoofed_memory.state == EffectState.REJECTED
        assert spoofed_memory.rejection_reason == "unsupported_capability_for_operation"
        assert "adapter.commit.started" not in [
            event["type"] for event in spoofed_memory_trace.events
        ]
        assert not memory_store_path(
            sample_memory_scope(root, approval_required=False),
            "project/spoofed-capability",
        ).exists()
        results["memory_capability_spoof_rejected"] = spoofed_memory.to_record()
        results["memory_capability_spoof_trace"] = spoofed_memory_trace.to_record()

        malformed_store_scope = sample_memory_scope(root, approval_required=False)
        malformed_store = memory_store_path(malformed_store_scope, "project/malformed")
        malformed_store.parent.mkdir(parents=True, exist_ok=True)
        malformed_store.write_text("1\n", encoding="utf-8")
        malformed_memory, malformed_memory_trace = evaluate_memory_write(
            malformed_store_scope,
            sample_memory_proposal("project/malformed"),
            approval_granted=True,
        )
        assert malformed_memory.state == EffectState.REJECTED
        assert malformed_memory.rejection_reason == "memory_store_unreadable"
        assert "adapter.commit.started" not in [
            event["type"] for event in malformed_memory_trace.events
        ]
        assert malformed_store.read_text(encoding="utf-8") == "1\n"
        results["memory_malformed_store_rejected"] = malformed_memory.to_record()
        results["memory_malformed_store_trace"] = malformed_memory_trace.to_record()

        malformed_shape_store_scope = sample_memory_scope(
            root,
            approval_required=False,
        )
        malformed_shape_store = memory_store_path(
            malformed_shape_store_scope,
            "project/malformed-shape",
        )
        malformed_shape_store.parent.mkdir(parents=True, exist_ok=True)
        malformed_shape_store.write_text("{}\n", encoding="utf-8")
        malformed_shape_memory, malformed_shape_trace = evaluate_memory_write(
            malformed_shape_store_scope,
            sample_memory_proposal("project/malformed-shape"),
            approval_granted=True,
        )
        assert malformed_shape_memory.state == EffectState.REJECTED
        assert malformed_shape_memory.rejection_reason == "memory_store_unreadable"
        assert "adapter.commit.started" not in [
            event["type"] for event in malformed_shape_trace.events
        ]
        assert malformed_shape_store.read_text(encoding="utf-8") == "{}\n"
        results["memory_malformed_shape_store_rejected"] = (
            malformed_shape_memory.to_record()
        )
        results["memory_malformed_shape_store_trace"] = (
            malformed_shape_trace.to_record()
        )

        bad_lifespan, bad_lifespan_trace = evaluate_memory_write(
            sample_memory_scope(root, approval_required=False),
            sample_memory_proposal(
                "project/bad-lifespan",
                content="invalid lifespan should reject\n",
                provenance=["test:bad-lifespan"],
                lifespan={"not": "serializable-as-v0-lifespan"},
            ),
            approval_granted=True,
        )
        assert bad_lifespan.state == EffectState.REJECTED
        assert bad_lifespan.rejection_reason == "memory_lifespan_invalid"
        assert "adapter.commit.started" not in [
            event["type"] for event in bad_lifespan_trace.events
        ]
        assert not memory_store_path(
            sample_memory_scope(root, approval_required=False),
            "project/bad-lifespan",
        ).exists()
        results["memory_lifespan_invalid_rejected"] = bad_lifespan.to_record()
        results["memory_lifespan_invalid_trace"] = bad_lifespan_trace.to_record()

        too_large_scope = Scope(
            scope_id="tiny_memory_scope",
            sandbox_root=root.resolve(),
            capabilities=frozenset({"memory.write"}),
            approval_required_for=frozenset(),
            max_bytes=256,
        )
        too_large_memory, too_large_trace = evaluate_memory_write(
            too_large_scope,
            sample_memory_proposal(
                "project/too-large-record",
                content="x",
                provenance=["p" * 600],
                lifespan="project",
            ),
            approval_granted=True,
        )
        assert too_large_memory.state == EffectState.REJECTED
        assert too_large_memory.rejection_reason == "input_too_large"
        assert "adapter.commit.started" not in [
            event["type"] for event in too_large_trace.events
        ]
        assert not memory_store_path(
            too_large_scope,
            "project/too-large-record",
        ).exists()
        results["memory_record_too_large_rejected"] = too_large_memory.to_record()
        results["memory_record_too_large_trace"] = too_large_trace.to_record()

        tampered_hash_scope = sample_memory_scope(root, approval_required=False)
        tampered_hash_store = memory_store_path(
            tampered_hash_scope,
            "project/tampered-hash",
        )
        tampered_hash_store.parent.mkdir(parents=True, exist_ok=True)
        tampered_hash_store.write_text(
            json.dumps(
                {
                    "record_id": "mem_tampered001",
                    "version": 1,
                    "target": "project/tampered-hash",
                    "content": "tampered content\n",
                    "lifespan": "project",
                    "provenance": ["test:tampered-hash"],
                    "actor": "agent:hermes",
                    "proposal_id": "prop_tampered_001",
                    "intent_id": "intent_tampered_001",
                    "trace_id": "trace_tampered",
                    "input_sha256": "0" * 64,
                    "committed_at": now_timestamp(),
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        tampered_hash_memory, tampered_hash_trace = evaluate_memory_write(
            tampered_hash_scope,
            sample_memory_proposal("project/tampered-hash"),
            approval_granted=True,
        )
        assert tampered_hash_memory.state == EffectState.REJECTED
        assert tampered_hash_memory.rejection_reason == "memory_store_unreadable"
        assert "adapter.commit.started" not in [
            event["type"] for event in tampered_hash_trace.events
        ]
        assert tampered_hash_store.read_text(encoding="utf-8").count("\n") == 1
        results["memory_tampered_hash_store_rejected"] = (
            tampered_hash_memory.to_record()
        )
        results["memory_tampered_hash_store_trace"] = tampered_hash_trace.to_record()

        reserved_suffix_memory, reserved_suffix_trace = evaluate_memory_write(
            sample_memory_scope(root, approval_required=False),
            sample_memory_proposal("project/foo.jsonl/bar"),
            approval_granted=True,
        )
        assert reserved_suffix_memory.state == EffectState.REJECTED
        assert (
            reserved_suffix_memory.rejection_reason
            == "memory_target_reserved_suffix"
        )
        assert "adapter.commit.started" not in [
            event["type"] for event in reserved_suffix_trace.events
        ]
        results["memory_reserved_suffix_target_rejected"] = (
            reserved_suffix_memory.to_record()
        )
        results["memory_reserved_suffix_target_trace"] = (
            reserved_suffix_trace.to_record()
        )

        old_umask = os.umask(0o444)
        try:
            restrictive_umask_scope = sample_memory_scope(
                root,
                approval_required=False,
            )
            restrictive_umask_memory, restrictive_umask_trace = evaluate_memory_write(
                restrictive_umask_scope,
                sample_memory_proposal("project/restrictive-umask"),
                approval_granted=True,
            )
        finally:
            os.umask(old_umask)
        assert restrictive_umask_memory.state == EffectState.COMMITTED
        restrictive_store = memory_store_path(
            restrictive_umask_scope,
            "project/restrictive-umask",
        )
        assert restrictive_store.read_text(encoding="utf-8").count("\n") == 1
        assert "adapter.commit.failed" not in [
            event["type"] for event in restrictive_umask_trace.events
        ]
        results["memory_restrictive_umask_commits_verified"] = (
            restrictive_umask_memory.to_record()
        )
        results["memory_restrictive_umask_trace"] = restrictive_umask_trace.to_record()

        bad_memory_target, bad_memory_target_trace = evaluate_memory_write(
            sample_memory_scope(root, approval_required=False),
            Proposal(
                proposal_id="prop_memory_bad_target_001",
                actor="agent:hermes",
                speech_act="intend",
                reason="malformed target should reject under governance",
                confidence=0.64,
                evidence=[],
                intent=Intent(
                    intent_id="intent_memory_bad_target_001",
                    proposal_id="prop_memory_bad_target_001",
                    adapter="memory",
                    operation="write",
                    target=123,
                    input={
                        "content": "should not commit\n",
                        "provenance": ["test:bad-target"],
                    },
                    required_capability="memory.write",
                ),
            ),
            approval_granted=True,
        )
        assert bad_memory_target.state == EffectState.REJECTED
        assert bad_memory_target.rejection_reason == "target_missing_or_not_string"
        assert "adapter.commit.started" not in [
            event["type"] for event in bad_memory_target_trace.events
        ]
        results["memory_target_not_string_rejected"] = bad_memory_target.to_record()
        results["memory_target_not_string_trace"] = bad_memory_target_trace.to_record()

        bad_memory_input, bad_memory_input_trace = evaluate_memory_write(
            sample_memory_scope(root, approval_required=False),
            Proposal(
                proposal_id="prop_memory_bad_input_001",
                actor="agent:hermes",
                speech_act="intend",
                reason="malformed input should reject under governance",
                confidence=0.63,
                evidence=[],
                intent=Intent(
                    intent_id="intent_memory_bad_input_001",
                    proposal_id="prop_memory_bad_input_001",
                    adapter="memory",
                    operation="write",
                    target="project/bad-input",
                    input=None,
                    required_capability="memory.write",
                ),
            ),
            approval_granted=True,
        )
        assert bad_memory_input.state == EffectState.REJECTED
        assert bad_memory_input.rejection_reason == "input_missing_or_not_object"
        assert "adapter.commit.started" not in [
            event["type"] for event in bad_memory_input_trace.events
        ]
        assert not memory_store_path(
            sample_memory_scope(root, approval_required=False),
            "project/bad-input",
        ).exists()
        results["memory_input_not_object_rejected"] = bad_memory_input.to_record()
        results["memory_input_not_object_trace"] = bad_memory_input_trace.to_record()

        memory_paused, memory_paused_trace = evaluate_memory_write(
            sample_memory_scope(root, approval_required=True),
            sample_memory_proposal("project/needs-approval"),
            approval_granted=False,
        )
        assert memory_paused.state == EffectState.PAUSED
        assert memory_paused.required_input == "approval_decision"
        assert "adapter.commit.started" not in [
            event["type"] for event in memory_paused_trace.events
        ]
        assert not memory_store_path(
            sample_memory_scope(root, approval_required=True),
            "project/needs-approval",
        ).exists()
        results["memory_approval_required_pauses"] = memory_paused.to_record()
        results["memory_approval_required_trace"] = memory_paused_trace.to_record()

        for result_key, rejected_target in {
            "memory_empty_target_rejected": "",
            "memory_dot_target_rejected": ".",
            "memory_path_escape_rejected": "../outside-scope",
        }.items():
            rejected_memory, rejected_memory_trace = evaluate_memory_write(
                sample_memory_scope(root, approval_required=False),
                sample_memory_proposal(rejected_target),
                approval_granted=True,
            )
            assert rejected_memory.state == EffectState.REJECTED
            assert rejected_memory.rejection_reason == "memory_target_outside_scope"
            assert "adapter.commit.started" not in [
                event["type"] for event in rejected_memory_trace.events
            ]
            results[result_key] = rejected_memory.to_record()
            results[f"{result_key}_trace"] = rejected_memory_trace.to_record()

        plain_target, plain_trace = evaluate_memory_write(
            sample_memory_scope(root, approval_required=False),
            sample_memory_proposal("project/collision"),
            approval_granted=True,
        )
        suffix_target, suffix_trace = evaluate_memory_write(
            sample_memory_scope(root, approval_required=False),
            sample_memory_proposal("project/collision.txt"),
            approval_granted=True,
        )
        assert plain_target.state == EffectState.COMMITTED
        assert suffix_target.state == EffectState.COMMITTED
        assert plain_target.acknowledgement is not None
        assert suffix_target.acknowledgement is not None
        assert plain_target.acknowledgement["store"] != suffix_target.acknowledgement[
            "store"
        ]
        results["memory_distinct_targets_do_not_collide"] = suffix_target.to_record()
        results["memory_distinct_targets_first_trace"] = plain_trace.to_record()
        results["memory_distinct_targets_second_trace"] = suffix_trace.to_record()

        interpret_target = root / "interpret-untouched.txt"
        assert not interpret_target.exists()
        interpret_file_approved, interpret_file_approved_trace = interpret(
            sample_scope(root, approval_required=False),
            sample_proposal("interpret-untouched.txt"),
            approval_granted=True,
        )
        assert interpret_file_approved.state == EffectState.APPROVED
        assert interpret_file_approved.acknowledgement is None
        assert interpret_file_approved.committed_at is None
        assert not interpret_target.exists()
        approved_event_types = [
            event["type"] for event in interpret_file_approved_trace.events
        ]
        assert "approval.granted" in approved_event_types
        assert "adapter.commit.started" not in approved_event_types
        assert "effect.committed" not in approved_event_types
        results["interpret_file_write_approved_without_committing"] = (
            interpret_file_approved.to_record()
        )
        results["interpret_file_write_approved_trace"] = (
            interpret_file_approved_trace.to_record()
        )
        results["interpret_file_write_approved_trace_events"] = approved_event_types

        interpret_pause_target = root / "interpret-pause.txt"
        assert not interpret_pause_target.exists()
        interpret_file_paused, interpret_file_paused_trace = interpret(
            sample_scope(root, approval_required=True),
            sample_proposal("interpret-pause.txt"),
        )
        assert interpret_file_paused.state == EffectState.PAUSED
        assert interpret_file_paused.required_input == "approval_decision"
        assert not interpret_pause_target.exists()
        paused_event_types = [
            event["type"] for event in interpret_file_paused_trace.events
        ]
        assert "approval.requested" in paused_event_types
        assert "adapter.commit.started" not in paused_event_types
        results["interpret_file_write_paused_without_committing"] = (
            interpret_file_paused.to_record()
        )
        results["interpret_file_write_paused_trace"] = (
            interpret_file_paused_trace.to_record()
        )

        interpret_reject_target = root / ".." / "outside-interpret-scope.txt"
        interpret_file_rejected, interpret_file_rejected_trace = interpret(
            sample_scope(root, approval_required=False),
            sample_proposal("../outside-interpret-scope.txt"),
            approval_granted=True,
        )
        assert interpret_file_rejected.state == EffectState.REJECTED
        assert interpret_file_rejected.rejection_reason == "path_outside_scope"
        rejected_event_types = [
            event["type"] for event in interpret_file_rejected_trace.events
        ]
        assert "adapter.commit.started" not in rejected_event_types
        results["interpret_file_write_rejected"] = interpret_file_rejected.to_record()
        results["interpret_file_write_rejected_trace"] = (
            interpret_file_rejected_trace.to_record()
        )

        interpret_non_intent, interpret_non_intent_trace = interpret(
            sample_scope(root, approval_required=False),
            Proposal(
                proposal_id="prop_interpret_non_intent_001",
                actor="agent:hermes",
                speech_act="claim",
                reason="not an effect intent",
                confidence=0.5,
                evidence=[],
            ),
            approval_granted=True,
        )
        assert interpret_non_intent.state == EffectState.REJECTED
        assert interpret_non_intent.rejection_reason == "proposal_is_not_an_intent"
        non_intent_events = [
            event["type"] for event in interpret_non_intent_trace.events
        ]
        assert "adapter.commit.started" not in non_intent_events
        results["interpret_non_intent_rejected"] = interpret_non_intent.to_record()
        results["interpret_non_intent_trace"] = interpret_non_intent_trace.to_record()

        interpret_unknown_adapter_proposal = Proposal(
            proposal_id="prop_interpret_unknown_adapter_001",
            actor="agent:hermes",
            speech_act="intend",
            reason="unsupported adapter for interpret",
            confidence=0.6,
            evidence=[],
            intent=Intent(
                intent_id="intent_interpret_unknown_adapter_001",
                proposal_id="prop_interpret_unknown_adapter_001",
                adapter="network",
                operation="post",
                target="https://example.invalid/",
                input={"body": ""},
                required_capability="network.post",
            ),
        )
        interpret_unknown, interpret_unknown_trace = interpret(
            sample_scope(root, approval_required=False),
            interpret_unknown_adapter_proposal,
            approval_granted=True,
        )
        assert interpret_unknown.state == EffectState.REJECTED
        assert (
            interpret_unknown.rejection_reason == "unsupported_adapter_for_interpret"
        )
        results["interpret_unsupported_adapter_rejected"] = (
            interpret_unknown.to_record()
        )
        results["interpret_unsupported_adapter_trace"] = (
            interpret_unknown_trace.to_record()
        )

        memory_ledger_root = root / ".fermata-memory"
        memory_files_before = (
            sorted(p.name for p in memory_ledger_root.glob("**/*.jsonl"))
            if memory_ledger_root.exists()
            else []
        )
        interpret_memory_approved, interpret_memory_approved_trace = interpret(
            sample_memory_scope(root, approval_required=False),
            sample_memory_proposal("project/interpret-only.txt"),
            approval_granted=True,
        )
        assert interpret_memory_approved.state == EffectState.APPROVED
        assert interpret_memory_approved.acknowledgement is None
        memory_files_after = (
            sorted(p.name for p in memory_ledger_root.glob("**/*.jsonl"))
            if memory_ledger_root.exists()
            else []
        )
        assert memory_files_after == memory_files_before
        memory_approved_events = [
            event["type"] for event in interpret_memory_approved_trace.events
        ]
        assert "approval.granted" in memory_approved_events
        assert "adapter.commit.started" not in memory_approved_events
        results["interpret_memory_write_approved_without_committing"] = (
            interpret_memory_approved.to_record()
        )
        results["interpret_memory_write_approved_trace"] = (
            interpret_memory_approved_trace.to_record()
        )

        from fermata.cli import (
            approval_from_record,
            proposal_from_record,
            run_effect,
            scope_from_record,
        )

        cli_scope_record = {
            "schema_version": "0.1",
            "record_type": "scope",
            "scope_id": "cli_self_test_scope",
            "resources": [{"kind": "file", "target": "./sandbox/cli-self-test.txt"}],
            "capabilities": [
                {
                    "name": "file.read",
                    "resource_kind": "file",
                    "mode": "read",
                    "allow": ["./sandbox/**"],
                },
                {
                    "name": "file.write",
                    "resource_kind": "file",
                    "mode": "write",
                    "allow": ["./sandbox/**"],
                },
            ],
            "approvals": [
                {
                    "authority": "performer",
                    "condition": 'effect.kind == "file.write"',
                }
            ],
            "audit": {"retain": ["trace", "approval", "input_hash", "actor"]},
        }
        cli_proposal_record = {
            "schema_version": "0.1",
            "record_type": "proposal",
            "proposal_id": "prop_cli_self_test_001",
            "actor": "agent:cli-self-test",
            "speech_act": "intend",
            "reason": "exercise the public CLI lowering path",
            "confidence": 0.82,
            "evidence": ["self-test:cli"],
            "payload": {"utterance": 'intend file.write target:"cli-self-test.txt"'},
            "intent": {
                "intent_id": "intent_cli_self_test_001",
                "proposal_id": "prop_cli_self_test_001",
                "adapter": "file",
                "operation": "write",
                "target": "cli-self-test.txt",
                "input": {"content": "CLI self-test writes through adapters only.\n"},
                "required_capability": "file.write",
            },
        }
        cli_approval_record = {
            "status": "approved",
            "authority": "performer",
            "approval_id": "approval_cli_self_test_001",
            "approver": "performer:self-test",
            "decided_at": "2026-06-15T12:00:00Z",
            "scope_id": "cli_self_test_scope",
            "intent_id": "intent_cli_self_test_001",
            "reason": "approve the checked CLI self-test example",
        }
        cli_root = root / "cli-self-test-sandbox"
        cli_scope = scope_from_record(cli_scope_record, sandbox_root=cli_root)
        cli_proposal = proposal_from_record(cli_proposal_record)
        cli_target = cli_root / "cli-self-test.txt"
        assert not cli_target.exists()
        cli_interpret_paused, cli_interpret_trace = run_effect(
            "interpret",
            cli_scope,
            cli_proposal,
        )
        assert cli_interpret_paused["state"] == "paused"
        assert cli_interpret_paused["required_input"] == "approval_decision"
        assert not cli_target.exists()
        cli_interpret_events = [
            event["type"] for event in cli_interpret_trace["events"]
        ]
        assert "approval.requested" in cli_interpret_events
        assert "adapter.commit.started" not in cli_interpret_events
        assert "effect.committed" not in cli_interpret_events
        results["cli_interpret_approval_required_pauses"] = cli_interpret_paused
        results["cli_interpret_approval_required_trace"] = cli_interpret_trace
        results["cli_interpret_approval_required_trace_events"] = (
            cli_interpret_events
        )

        cli_run_committed, cli_run_trace = run_effect(
            "run",
            cli_scope,
            cli_proposal,
            approval=approval_from_record(cli_approval_record),
        )
        assert cli_run_committed["state"] == "committed"
        assert cli_target.exists()
        assert cli_target.read_text(encoding="utf-8") == (
            "CLI self-test writes through adapters only.\n"
        )
        cli_run_events = [event["type"] for event in cli_run_trace["events"]]
        assert "adapter.commit.started" in cli_run_events
        assert "effect.committed" in cli_run_events
        results["cli_run_approved_commits"] = cli_run_committed
        results["cli_run_approved_trace"] = cli_run_trace
        results["cli_run_approved_trace_events"] = cli_run_events

        from fermata.policy_parser import (
            PolicyParseError,
            parse_agent_proposal_json,
            parse_policy_block,
        )

        authority_policy_text = (
            "scope charter_note_sandbox {\n"
            '  resource file "./sandbox/charter-note.txt"\n'
            '  capability file.read on "./sandbox/**"\n'
            '  capability file.write on "./sandbox/**"\n'
            "  policy deny if path.outside_scope\n"
            '  approval require performer if effect.kind == "file.write"\n'
            "  audit retain trace, input_hash, output_hash, actor, approval\n"
            "}\n"
        )
        scope_record = parse_policy_block(authority_policy_text)
        assert scope_record["record_type"] == "scope"
        assert scope_record["scope_id"] == "charter_note_sandbox"
        assert len(scope_record["resources"]) == 1
        assert scope_record["resources"][0]["kind"] == "file"
        assert {c["name"] for c in scope_record["capabilities"]} == {
            "file.read",
            "file.write",
        }
        assert scope_record["policies"][0]["effect"] == "deny"
        assert scope_record["approvals"][0]["authority"] == "performer"
        assert "trace" in scope_record["audit"]["retain"]
        results["authority_policy_parses_to_scope_record"] = scope_record

        agent_json = (
            "{\n"
            '  "schema_version": "0.1",\n'
            '  "record_type": "proposal",\n'
            '  "proposal_id": "prop_surface_test_001",\n'
            '  "actor": "agent:hermes",\n'
            '  "speech_act": "intend",\n'
            '  "reason": "split-surfaces kata",\n'
            '  "confidence": 0.81,\n'
            '  "evidence": ["scope:charter_note_sandbox"],\n'
            '  "payload": {"utterance": "intend file.write target:\\"./sandbox/note.txt\\""},\n'
            '  "intent": {\n'
            '    "intent_id": "intent_surface_test_001",\n'
            '    "proposal_id": "prop_surface_test_001",\n'
            '    "adapter": "file",\n'
            '    "operation": "write",\n'
            '    "target": "./sandbox/note.txt",\n'
            '    "input": {"content": "boring proof\\n"},\n'
            '    "required_capability": "file.write"\n'
            "  }\n"
            "}\n"
        )
        proposal_record = parse_agent_proposal_json(agent_json)
        assert proposal_record["record_type"] == "proposal"
        assert proposal_record["speech_act"] == "intend"
        assert proposal_record["intent"]["adapter"] == "file"
        assert proposal_record["intent"]["target"] == "./sandbox/note.txt"
        assert "state" not in proposal_record
        assert "acknowledgement" not in proposal_record
        results["agent_json_parses_to_proposal_record"] = proposal_record

        injected_agent_json = (
            "{\n"
            '  "schema_version": "0.1",\n'
            '  "record_type": "proposal",\n'
            '  "proposal_id": "prop_surface_inject_001",\n'
            '  "actor": "agent:hermes",\n'
            '  "speech_act": "claim",\n'
            '  "payload": {"utterance": "claim something"},\n'
            '  "state": "committed",\n'
            '  "acknowledgement": {"adapter": "file", "target": "x", "handle": "x"}\n'
            "}\n"
        )
        injected_record = parse_agent_proposal_json(injected_agent_json)
        results["agent_cannot_inject_committed_state"] = {
            "record_with_injection": injected_record,
        }

        try:
            parse_policy_block(
                "scope denied_inline {\n"
                "  resource file \"./x\"\n"
                "  capability file.write on \"./x\"\n"
                "  approval grant performer always\n"
                "}\n"
            )
        except PolicyParseError as exc:
            results["authority_policy_cannot_inline_grant"] = {
                "rejected": True,
                "error": str(exc),
            }
        else:
            raise AssertionError(
                "authority policy parser must reject 'approval grant ...'; "
                "the authority surface declares requirements, not granted approvals"
            )

    return results


def main() -> None:
    """Run the spike self-tests and print JSON evidence."""

    results = run_self_tests()
    print(json.dumps(results, indent=2, sort_keys=True))
