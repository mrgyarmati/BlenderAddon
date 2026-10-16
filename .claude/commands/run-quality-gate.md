---
description: Run every quality gate and report a pass/fail checklist with evidence
---

Run `py -3 scripts/verify_release.py` from the repository root (add `--skip-unreal` only if asked to).

It runs unit tests (system Python and Blender's bundled Python), the plugin sync check, Blender integration tests
from source, extension validate/build/zip-validate/audit, Blender integration tests against the built zip, and the
Unreal 5.8 and 5.6 acceptance runs.

Report the RELEASE CHECKLIST it prints verbatim. For every FAIL, open the relevant log (build/acceptance_logs/,
the export log in the failing export folder) and give the root cause with file:line. Never describe a SKIPPED gate
as passed.
