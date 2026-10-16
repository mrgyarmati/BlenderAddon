---
description: Prepare a release: version bump, changelog, full gate, artifacts
argument-hint: <version>
---

Prepare release $ARGUMENTS.

1. Set the version in addon/unreal_exporter/blender_manifest.toml, constants.ADDON_VERSION, the importer
   (`IMPORTER_VERSION` in unreal_templates/importer_core.py), unreal/BlenderBridge/BlenderBridge.uplugin and
   pyproject.toml; run `py -3 scripts/sync_unreal_plugin.py`.
2. Move the CHANGELOG.md "Unreleased" entries under the new version with today's date.
3. Run `py -3 scripts/verify_release.py`. UE 5.8 must pass; UE 5.6 must pass before claiming 5.6+ support.
4. Attach as release evidence: dist/unreal_exporter-<version>.zip, build/acceptance_logs/ue_5.8_result.json and
   ue_5.6_result.json, and the RELEASE CHECKLIST output.
5. Do not commit, tag or push unless asked.

Report the checklist, artifact paths and anything that blocked the release.
