# Changelog

All notable changes to this project are documented here. The format follows Keep a Changelog; versions follow
Semantic Versioning.

## [Unreleased]

## [0.1.0] - 2026-10-16

### Added
- Blender 5.2 extension `unreal_exporter` ("Unreal Export Bridge") with an "Unreal Export" N-panel.
- Export profiles: Static Mesh, Skeletal Mesh (optionally with animations), Animation, Collection Scene; scopes:
  selected objects, active collection, chosen collections; one asset per object or per collection.
- Staged, non-destructive export in a temporary centimetre scene; Blender's FBX exporter writes one file per asset.
- Validation catalogue with blocking errors, warnings, info and safe fixes with preview (rename helpers, repair
  duplicated export ids, remove empty material slots).
- Collision helpers (UBX/USP/UCP/UCX, convex cylinder) fitted to objects or edit-mode selections; optional
  automatic Unreal collision for meshes without helpers (default on).
- Sockets at the 3D cursor, origin, selection median, active vertex/bone or from existing empties, with an Unreal
  transform preview.
- Generated (Decimate, non-destructive) and authored LODs, presets, triangle statistics and a side-by-side audit.
- Skeletal export with morph targets; per-action animation export baked from an evaluation copy of the rig with
  root-motion (keep, root bone, in place, object to root) and NLA policies.
- Batch rename of assets and every linked helper with conflict preview.
- Versioned JSON manifest (schema 1) with migration support, export logs with path redaction, deterministic plan ids
  and content hashes.
- Generated `import_to_unreal.py` with Unreal 5.6/5.8 adapters, explicit Interchange pipelines, checksum verification,
  socket reconciliation, collision/LOD verification, Blender-id based reimport mapping and JSON import receipts.
- Optional Unreal plugin `BlenderBridge` exposing the importer as `blender_bridge.import_manifest()`.
- Unit, Blender integration and Unreal 5.6/5.8 acceptance test suites; release gate script.

### Verified
- Blender 5.2.0 LTS; Unreal Engine 5.8.3 and 5.6.1 (95 acceptance checks each, see docs/test-matrix.md).
- Install/enable/disable/uninstall in an isolated profile; undo/redo and the modal export in a GUI session.
