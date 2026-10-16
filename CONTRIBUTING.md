# Contributing

## Clean-room rule

This project is an independent implementation built only from documented workflows and public interoperability
conventions (Blender's Python API and bundled FBX exporter, Unreal's documented FBX/Interchange behaviour and its
Python API, and measurements of what those tools actually do).

- Do **not** inspect, decompile, copy or imitate the source code, private assets, wording, icons or distinctive UI
  layout of any commercial Blender-to-Unreal product, including the one used as a feature reference in the original
  plan.
- Do not paste code from such products into issues, pull requests or prompts.
- Reading Blender's and Unreal's own source and Python API to understand interoperability behaviour is fine; record
  findings as measurements in `docs/compatibility.md`, not as copied code.

By contributing you confirm that your contribution follows this rule and is licensed under GPL-3.0-or-later.

## Workflow

1. Write a failing test first (see `docs/test-matrix.md` for which layer to use).
2. Keep `domain/` free of Blender imports; keep Unreal calls inside `unreal_templates/importer_core.py`.
3. Every bug fix needs a regression test.
4. Run `py -3 scripts/verify_release.py` before asking for review (or explain which gate you could not run).
5. Update `CHANGELOG.md` and the relevant docs.
