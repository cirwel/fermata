# Fermata Local Alpha v0.1.1 Tag Checklist

**Created:** June 17, 2026
**Last Updated:** June 17, 2026
**Status:** Active tag checklist

---

> **Agents may propose; only governed effects may commit.**

This checklist is the source-control publication gate for the local-alpha
release notes in `docs/releases/local-alpha-v0.1.1.md`. The `v0.1.1` tag has not
been created or pushed. Keep this file as the active gate until the tag effect
occurs, then mark it historical.

## Tag Identity

- Package version: `0.1.1`
- Intended tag: `v0.1.1`
- Release notes: `docs/releases/local-alpha-v0.1.1.md`
- Required validator: `python3 scripts/validate_local_alpha.py`
- Release-candidate dry run: `python3 scripts/check_local_alpha_release_candidate.py`
- Release-candidate record: `references/release-candidates-v0/local-alpha-v0.1.1-rc1.json`
- Tag approval packet: `references/release-approvals-v0/local-alpha-v0.1.1-tag-approval-packet.json`
- Tag publication preflight: `python3 scripts/check_local_alpha_tag_publication_preflight.py --approval-reference <approval-reference>`
- Release commit: `71ec78ca39291dd7cc4a923703ba880cb668cbb4` (PR #45 merge on `main`)

## Required Checks

- [ ] Confirm the release commit is on `main` and matches `origin/main`.
- [ ] Confirm `git status --short --branch` is clean.
- [ ] Upgrade the release-candidate record from `pending_ci` to
      `pre_tag_candidate` with the merged commit and at least two green CI run
      URLs.
- [ ] Run `python3 scripts/check_local_alpha_release_artifacts.py`.
- [ ] Run `python3 scripts/check_local_alpha_release_candidate.py` from a clean
      `main` checkout matching `origin/main`.
- [ ] Run `python3 scripts/check_local_alpha_release_candidate_record.py`.
- [ ] Run `python3 scripts/check_local_alpha_tag_approval_packet.py`.
- [ ] Run `python3 scripts/check_local_alpha_tag_publication_preflight.py --approval-reference <approval-reference>`.
- [ ] Run `python3 scripts/validate_local_alpha.py` and attach the top-level
      `"status": "passed"` result.
- [ ] Confirm GitHub Actions `ci / golden` passed on the exact release commit.
- [ ] Confirm the package build gate reports wheel and sdist artifacts for
      version `0.1.1`.
- [ ] Confirm `docs/releases/local-alpha-v0.1.1.md` names the same package
      version, tag, validator command, and non-claims as this checklist.
- [ ] Confirm no generated CLI smoke outputs, temporary build outputs, local
      service records, or recovery drill scratch files are staged.
- [ ] Confirm no secrets, credentials, tokens, passwords, or connection strings
      are present.
- [ ] Confirm maintainer approval to create and push the tag.
- [ ] Record the approval reference in the release handoff before running the
      tag commands.

## Tag Command

Run these commands only after every required check completes and the maintainer
approves the source-control publication effect:

```bash
git tag -a v0.1.1 -m "Fermata local alpha v0.1.1"
git push origin v0.1.1
```

## Tag Evidence To Keep

- release commit SHA;
- tag object SHA after creation;
- `python3 scripts/validate_local_alpha.py` output summary;
- GitHub Actions `ci / golden` URL for the release commit;
- package build checker summary;
- release-candidate dry-run summary;
- release-candidate record summary;
- tag approval packet summary;
- tag publication preflight summary;
- maintainer approval reference.

## Roll-Forward Rule

If any required check fails after the tag is created locally but before it is
pushed, delete the local tag and fix forward on a new commit. Do not retarget a
pushed tag without an explicit maintainer decision record; post-publication
fixes are handled by fix-forward commits on `main`, not by retagging.
