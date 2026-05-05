## Summary

- 

## Contribution Type

- [ ] docs
- [ ] schema / IR
- [ ] runtime code
- [ ] parser / renderer
- [ ] tests / golden fixtures
- [ ] examples / katas

## Agent/Model Involvement

- Implementer:
- Reviewer:
- Human steward:
- Scope granted:
- Effects performed:
- Evidence produced:
- Uncertainty or deferred questions:

> Do not include hidden chain-of-thought. Use structured rationale, assumptions,
> evidence, decisions, and doubts instead.

## Governed-Effect Boundary Check

- [ ] The change preserves proposal vs intent vs committed effect.
- [ ] The change does not widen capabilities or authority silently.
- [ ] Denial, pause, or rejection paths are represented where relevant.
- [ ] No secrets, credentials, tokens, passwords, or connection strings are included.

## Verification

- [ ] `python3 -m compileall scripts src`
- [ ] `python3 -m json.tool references/governed-effect-ir-v0.schema.json >/tmp/fermata_schema.json`
- [ ] `python3 -m json.tool references/tongue-golden-tests-v0.json >/tmp/fermata_golden.json`
- [ ] `python3 scripts/run_tongue_golden_tests.py`
- [ ] Manual review only; reason:

## Notes for Reviewer

- 
