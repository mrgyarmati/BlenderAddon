# Architecture

## Layers

```
addon/unreal_exporter/
  domain/            pure Python: records, naming, discovery, validation, planning, unreal_math   (no bpy)
  services/          adapters and pipeline: snapshot, staging, animation, FBX writing, helpers
                     (manifest.py, logging.py, unreal_script.py are pure too)
  operators/         thin bpy.types.Operator wrappers calling services; report to the user
  panels/            N-panel "Unreal Export" (draw code reads state only)
  unreal_templates/  importer_core.py -- runs inside Unreal, embedded into import_to_unreal.py
unreal/BlenderBridge optional Unreal plugin exposing the same importer as `blender_bridge`
```

Scene data enters the domain as an immutable `SceneSnapshot` (`services/scene_snapshot.py`), so discovery,
validation and planning are unit-tested without Blender. Unreal API calls exist only in `importer_core.py`.

## Pipeline

| Stage | Module | Notes |
|---|---|---|
| 1 Discover | `domain/discovery.py` | scope → roots; helpers resolved over the whole scene |
| 2 Classify | `domain/discovery.py` | static / skeletal / animation by profile and armature deformation |
| 3 Validate | `domain/validation.py` (+ `services/mesh_stats.py`) | structured `ValidationIssue`s |
| 4 Plan | `domain/planning.py` | immutable `ExportPlan`, deterministic `plan_id`, FBX options per kind |
| 5 Stage | `services/staging.py`, `services/animation.py` | temporary scene + export collection |
| 6 Normalize | same | centimetres, pivot, baked transforms, helper names, socket compensation, baked animation |
| 7 Write | `services/fbx_export.py` | Blender's FBX exporter, atomic temp-file + rename |
| 8 Manifest | `services/manifest.py` | schema 1, checksums, content hashes |
| 9 Import | `services/unreal_script.py`, `importer_core.py` | generated script or plugin |
| 10 Restore/clean | `StagingSession.cleanup`, `ContextGuard` | always in `finally` |
| 11 Report | `services/logging.py`, `operators/common.py` | text + JSONL logs, Results panel |

`services/export_service.py` orchestrates: `prepare()` runs stages 1–4 (it only writes missing export ids);
`ExportJob` runs 5–8 one asset per `step()` so the operator can show progress and cancel with Esc; `finish()` writes
the manifest, script and logs and restores the context.

## Staging

- One `StagingSession` per asset: a temporary scene (`__uex_stage`, unit scale 0.01, the user's fps and current
  frame) with an export collection. Every datablock it creates is tracked and removed in `cleanup()`.
- Sources are evaluated through `evaluation_copy()`: a visible, unparented, unanimated copy with the same world
  matrix (Blender skips hidden objects). Geometry is copied with `meshes.new_from_object`, transformed into staged
  centimetre space (`Scale(100·unit) @ pivot⁻¹ @ world`), faces flipped for negative scale, material slots assigned
  in place.
- FBX node names are object names, which are unique per file. `NameJournal.claim()` moves a source datablock that
  holds a needed name to `<name>.uexsrc###` and restores it in reverse order in `cleanup()`; tests assert names and a
  deep scene fingerprint are unchanged after success, cancellation and forced failure.
- Skeletal assets: armature data is copied and transformed into staged space; the staged object is named
  `Armature`; meshes are evaluated without armature deformation (or copied raw with shape keys for morph targets) and
  re-bound to the staged armature.
- Animation: an evaluation copy of the source rig (constraints, drivers, IK; self-references remapped) is sampled in
  the staging scene for the chosen action (NLA muted) or the scene result; armature-space bone matrices are mapped
  into staged space (per frame for "Object to Root") and converted to local keys under full inheritance; keys start
  at FBX time 0.
- Exports run with `bpy.context.temp_override(scene=staging, view_layer=…)` and an explicit `collection=` so exactly
  the staged objects are written. The user's scene, selection, frame and mode are never used by the exporter.

## Context restoration

`ContextGuard` captures mode, active object, selection, frame/subframe, active collection, per-object visibility
flags and `matrix_basis`, switches to Object Mode (flushing edit-mode data) and restores everything in `__exit__`,
including after exceptions. Operators that touch the scene run inside it.

## Unreal side

`importer_core.py` (standard library + `unreal`) reads the manifest, selects `Adapter56` or `Adapter58` from
`SystemLibrary.get_engine_version()`, and for each asset: verifies the FBX checksum, chooses the engine-specific file
(`file_variants`), builds an `InterchangeGenericAssetsPipeline` with every relevant option set explicitly, imports
through `AssetImportTask` (automated, synchronous, replace existing, `APPLY_NO_PROPERTIES` reimport strategy),
reconciles sockets, verifies collision and LOD counts, sets root motion, tags the asset with its Blender source id,
and writes `unreal_import_receipt.json`. Failures are per asset; the run continues.

### Reimport mapping

Every exported object/collection/action carries a persistent UUID (`id.uex.uuid`). The importer stores
`source id → Unreal path` in `<Project>/Saved/BlenderBridge/source_index.json` and as asset metadata
(`BlenderBridge.SourceId`). Re-exporting after a Blender rename finds the earlier asset by id:
*Update Existing* (default) reimports it in place, *Follow Rename* renames it in Unreal first. Duplicated objects get
fresh ids automatically (the copy whose name matches the recorded `uuid_name_hint` keeps the original id).

## Validation catalogue

Blocking errors (export refused unless Developer Mode is on in the preferences):

| Code | Meaning |
|---|---|
| E_DUPLICATE_UNREAL_PATH | two assets map to the same Unreal path (case-insensitive) |
| E_INVALID_NAME | empty or reserved name after sanitization; unusable socket name |
| E_MISSING_DATA | no polygons, no bones/deform bones, armature without meshes |
| E_MISSING_ARMATURE / E_MULTIPLE_ARMATURES | skeletal asset without, or with several, root armatures |
| E_MULTIPLE_ROOT_BONES / E_DUPLICATE_BONES | several exported root bones; names equal ignoring case or clashing with `Armature` |
| E_UNWEIGHTED_VERTICES | skinned vertices without deform weights |
| E_ANIM_NO_SKELETON / E_FRAME_RANGE / E_NO_ACTION / E_SAMPLE_STEP | unusable animation setup |
| E_LOD_MISSING_LOD0 / E_LOD_DUPLICATE_INDEX / E_LOD_SKELETON_MISMATCH | broken LOD chain |
| E_COLLISION_OWNER_MISSING / E_COLLISION_NAME_MISMATCH | collision not associated with exactly one render mesh |
| E_DUPLICATE_SOCKET | two sockets export with the same name |
| E_OUTPUT_OUTSIDE_ROOT / E_PATH_UNWRITABLE / E_EXPORT_ROOT_MISSING | output path problems |
| E_UNREAL_ROOT / E_NO_ASSETS / E_PROFILE / E_COLLECTION_MISSING / E_NO_ACTIVE_COLLECTION / E_NO_COLLECTIONS | setup |

Warnings: W_UNAPPLIED_TRANSFORM, W_NEGATIVE_SCALE, W_NON_UNIFORM_SCALE, W_NON_MANIFOLD, W_DEGENERATE_FACES,
W_MISSING_UV0, W_LIGHTMAP_UV_OVERLAP, W_MATERIAL_SLOTS, W_EMPTY_MATERIAL_SLOT, W_NGONS, W_SOCKET_FAR,
W_SOCKET_NAME_MISMATCH, W_LOD_TRIS_NOT_DECREASING, W_LOD_GAP, W_LOD_OFFSET, W_LOD_MATERIALS, W_LOD_NAME_MISMATCH,
W_BONE_INFLUENCES, W_SHAPE_KEYS_DISABLED, W_MORPH_WITH_MODIFIERS, W_MATERIALS_REQUESTED, W_PRIMITIVE_DEFORMED,
W_PRIMITIVE_SCALE, W_UCX_NOT_CONVEX, W_UCX_OPEN, W_ARMATURE_OBJECT_ANIMATED, W_DUPLICATE_UUID, W_LONG_PATH,
W_HELPER_OWNER_MISSING, W_ACTION_MISSING, W_LOD_IGNORED_*, W_FRAME_RANGE_SINGLE. Info: I_* (sanitized names,
resolved helpers, skipped objects).

Safe fixes are separate commands with a preview dialog and undo: rename helpers to match their owner, repair
duplicated export ids, remove empty material slots.

## Determinism

`plan_id` is a SHA-256 over the canonical plan (assets, import options, settings) excluding absolute paths and
timestamps. Each asset also gets `source_hash`, a SHA-256 of the staged data actually written (vertices, topology,
UVs, materials, weights, shape keys, bones, keys). FBX bytes contain timestamps, so `file_sha256` is only used as an
integrity check by the importer. Exporting an unchanged scene twice yields identical plans and manifests apart from
`created_at` and `file_sha256` (`manifest.semantic_view`).

## Safety

- Output paths are built with `naming.safe_join` and must stay inside the export folder (and inside the optional
  permitted roots from the preferences).
- Logs are export-root relative unless *Absolute Paths in Logs* is enabled.
- No network access, no background listeners, no handlers or timers outside a running export.
