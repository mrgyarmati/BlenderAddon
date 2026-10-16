---
description: Implement one vertical slice of the plan with tests first
argument-hint: <feature> [phase]
---

Implement this single slice: $ARGUMENTS

1. Read CLAUDE.md, docs/architecture.md and docs/compatibility.md; locate the modules involved.
2. Write or extend failing tests first: a unit test for pure logic (tests/unit), a Blender integration test
   (tests/blender) for anything touching bpy, and an Unreal acceptance check (scripts/make_fixture_files.py +
   tests/unreal/acceptance.py) when Unreal behaviour is involved.
3. Implement the smallest change that passes. Keep bpy out of domain/; keep Unreal API calls in
   unreal_templates/importer_core.py behind Adapter56/Adapter58; no new runtime dependencies; never mutate source
   objects (stage copies).
4. Run, in order: unit tests, `py -3 scripts/run_blender_tests.py`, and `py -3 scripts/run_unreal_tests.py` if Unreal
   behaviour changed. If importer_core.py changed, run `py -3 scripts/sync_unreal_plugin.py`.
5. Update docs (and CHANGELOG.md) when behaviour changes.

Report: files changed, design decisions, commands run with their result lines, skipped gates with reasons, risks.
