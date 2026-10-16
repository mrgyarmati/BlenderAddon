# Project mission
Clean-room Blender 5.2 extension (`addon/unreal_exporter`) for reliable FBX export to Unreal Engine 5.6–5.8, with a
JSON manifest and a generated Unreal Python importer. UE 5.8 is the release gate; 5.6 must also pass for "5.6+".

# Non-negotiable rules
- Never inspect or copy proprietary competitor code, assets, text, icons or UI (see CONTRIBUTING.md).
- Preserve source scenes: export only through staged copies (`services/staging.py`); restore names via `NameJournal`.
- Keep `domain/` (and services/manifest.py, logging.py, unreal_script.py) free of bpy; Unreal API calls live only in
  `unreal_templates/importer_core.py` behind `Adapter56`/`Adapter58`.
- Intra-package imports are relative (installed as `bl_ext.<repo>.unreal_exporter`).
- No third-party runtime dependencies. No network activity.
- Do not claim compatibility without passing tests in the named versions.
- Every bug fix gets a regression test. Every scene-touching operation restores context (`ContextGuard`) in finally.
- Never silently rename, modify, delete or overwrite user data. Draw code never writes data.
- Edit `addon/.../unreal_templates/importer_core.py`, never the plugin copy; then run `scripts/sync_unreal_plugin.py`.

# Commands (Windows: `py -3`; elsewhere `python3`)
- Unit: `py -3 -m unittest discover -s tests/unit -t .`   (pytest also works: `python -m pytest tests/unit -q`)
- Blender: `py -3 scripts/run_blender_tests.py [-k PATTERN]`  (wraps `blender --background --factory-startup
  --python-exit-code 1 --python tests/blender/run_all.py`; set BLENDER_EXE if Blender is not auto-detected)
- Validate: `blender --factory-startup --command extension validate addon/unreal_exporter`
- Build: `py -3 scripts/build_extension.py`  (build + zip validate + content audit into dist/)
- Unreal acceptance: `py -3 scripts/run_unreal_tests.py [--versions 5.8 5.6]`  (UE_5_8_EDITOR / UE_5_6_EDITOR override)
- Quality gate: `py -3 scripts/verify_release.py`
- Always pass `--factory-startup` to Blender: the user profile loads third-party add-ons.

# Workflow
1. Read docs/architecture.md and docs/compatibility.md (measured Unreal/Blender quirks) for the area you touch.
2. Write or update failing tests first (unit, Blender integration, Unreal acceptance as relevant).
3. Implement the smallest vertical slice.
4. Run unit tests, Blender tests, extension validation, and the Unreal gate when importer/FBX output changes.
5. Update docs and CHANGELOG.md when behaviour changes.
6. Report changed files, commands run with result lines, skipped gates with reasons, risks and follow-ups.

# Definition of done
Code, tests, error handling, docs and compatibility notes are complete; no placeholders or swallowed exceptions.
