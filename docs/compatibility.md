# Compatibility

## Supported and verified versions

| Component | Supported | Verified with | Evidence |
|---|---|---|---|
| Blender | 5.2 LTS (`blender_version_min = "5.2.0"`) | 5.2.0 LTS (hash fbe6228777e7) | unit + Blender integration suites |
| Unreal Engine (release gate) | 5.8 | 5.8.3 (CL 58210709) | 95/95 acceptance checks |
| Unreal Engine | 5.6 | 5.6.1 (CL 44394996) | 95/95 acceptance checks |
| Unreal Engine 5.7 | expected (uses the 5.6 adapter) | **not tested** | — |
| Python in Blender | bundled 3.13 | 3.13 | unit suite runs under Blender's Python too |
| Platforms | Windows verified; export code is platform-neutral | Windows 11 | — |

Do not advertise a version that has not passed `scripts/run_unreal_tests.py`.

## Coordinate system, units and pivots

- Blender `(x, y, z)` metres import into Unreal as `(x, -y, z)` centimetres with the exporter's default axes
  (forward `-Z`, up `Y`): X is preserved, Y is mirrored (handedness). The acceptance reference cube (markers at
  +X and +Y) lands with bounds `(-50, -60, -50)..(75, 50, 50)` cm in both engines.
- Assets are staged in a temporary scene with unit scale 0.01 and geometry scaled by `100 × scene unit scale`, so the
  FBX carries **no node scale**. Without this, Blender's default export gives every skeleton bone and every socket a
  scale of 100 in Unreal (measured in 5.6.1 and 5.8.3, with both `FBX_SCALE_NONE` and `FBX_SCALE_ALL`).
- Pivot: the asset root's origin (object mode) or the collection instance offset; "World Origin" keeps placement.
  Object rotation and scale are baked into the exported geometry, so Unreal's local axes follow the world axes; a
  warning reports unapplied rotation/scale.
- Rotations in the manifest and socket preview use Unreal's `FQuat::Rotator` convention (roll, pitch, yaw), after
  conjugating by the Y mirror. Compare rotations as matrices: at ±90° pitch, roll/yaw split differently per engine.

## Measured Unreal behaviour the design depends on

| # | Finding (5.6.1 and 5.8.3 unless noted) | Response |
|---|---|---|
| U1 | FBX import goes through Interchange by default (`Interchange.FeatureFlags.Import.FBX = true`). | Importer configures Interchange pipelines. |
| U2 | Passing `FbxImportUI` options converts them, setting `bCollision = bAutoGenerateCollision`; `bImportCollisionAccordingToMeshName` is gated on `bCollision`, so turning auto-collision off also drops custom UCX collision. | Importer builds an `InterchangeGenericAssetsPipeline` itself and passes it via `InterchangePipelineStackOverride`. |
| U3 | 5.8 replaced `combine_static_meshes`/`combine_skeletal_meshes` (bool) with `*_behavior` enums and `snap_to_closest_frame_boundary` with `frame_alignment`. | `Adapter56` / `Adapter58`. |
| U4 | 5.8 deprecates `auto_detect_mesh_type`; setting it raises. | Never set; mesh type is forced with `force_all_mesh_as_type`. |
| U5 | An FBX root node named exactly `Armature` is dropped; any other armature name becomes an extra root bone. | Staged armature object is named `Armature`. |
| U6 | Sockets come in rotated by −90° about their local X axis (identity → roll −90; Blender X+90 → identity). | Staged sockets are pre-rotated +90° about local X; manifest stores the expected transform. |
| U7 | With an FBX LOD group, 5.8 matches collision against the **group** name and needs the hull at the root; 5.6 matches the **LOD0** name and needs the hull **under LOD0**. An unmatched `UCX_` mesh is imported as render geometry (extra triangles and a `Material_0` slot), and 5.6 also merges root-level hulls into LOD1+. | `PER_ENGINE` (default): main FBX in the 5.8 layout plus `<name>.ue56.fbx` in the 5.6 layout; the importer picks by engine. Single-engine layouts are selectable. |
| U8 | 5.8 imports no sockets for LOD-group assets (5.6 imports sockets that are children of LOD0). | Importer reconciles sockets from the manifest (adds missing ones, corrects drifted ones) and reports it. |
| U9 | Collision name matching compares `UCX_<body>` with a node name; for a mesh whose scene node has children, 5.8 uses the geometry name. | Staged mesh datablocks are named exactly like their objects. |
| U10 | Unreal fits a `UCP_` capsule from the farthest vertex pair (O(n²)) and the max distance to that axis. | Capsule helpers have single pole vertices and few vertices. |
| U11 | `KConvexElem` exposes no geometry to Python (ElemBox/VertexData not reflected, Transform protected); `export_text()` includes them. | Acceptance test reads hull bounds from `export_text()`. |
| U12 | In `-run=pythonscript` commandlets, `get_editor_subsystem()` returns None. | Importer uses only function libraries and object APIs. |
| U13 | `-Script=` paths with spaces break the commandlet's argument parsing. | Test runner refuses paths with spaces. |
| U14 | Reimport over an existing asset with `ReimportStrategyFlags.APPLY_NO_PROPERTIES` keeps editor-assigned materials and sockets. | Default reimport strategy; acceptance-tested. |
| U15 | `fallback_collision_type` adds an automatic hull. | Set per asset: only for static meshes without collision helpers (setting *Collision When Missing*, default on), so custom hulls are never doubled; acceptance-tested. |
| U16 | Skeletal LOD groups (LodGroup under the armature) import as skeletal LODs in both engines. | Supported for single-mesh skeletal assets; acceptance-tested (2 LODs). |
| U17 | 5.8 no longer reflects `SkeletalMesh.LODInfo`; `EditorSkeletalMeshLibrary.get_lod_count` works in both engines and in commandlets. | Used by the acceptance test. |
| U18 | `EditorAssetLibrary.rename_asset` moves an asset; *Follow Rename* leaves exactly one static mesh at the new path. | Acceptance-tested. |

## Measured Blender 5.2 behaviour

| # | Finding | Response |
|---|---|---|
| B1 | Re-assigning the action slot that `AnimData.action = …` already auto-assigned crashes Blender 5.2.0 (null read in `foreach_action_slot_use_with_references`). | `animation.assign_slot` assigns only when different. |
| B2 | Hidden objects are not evaluated; `evaluated_get()` of a hidden LOD/collision returns no geometry. | Sources are evaluated through visible copies in the staging scene (`evaluation_copy`, `EvaluationScene`). |
| B3 | `Mesh.materials.clear()` resets every face's material index to 0. | Staged material slots are assigned in place. |
| B4 | The FBX exporter writes scene-animation keys at absolute times (frame 1 → 1/fps) and Blender's importer adds a 1-frame offset. | Animation keys are written relative to the first exported frame (FBX time 0). |
| B5 | A new armature object has no `pose` until the depsgraph evaluates it once; relations for newly linked objects need `view_layer.update()`. | Staging forces an update before reading poses. |
| B6 | FBX node names are object names, which are unique per file. | `NameJournal` temporarily renames source datablocks that hold a needed name and restores them in `finally`. |
| B7 | Background Blender with the user profile loads third-party add-ons. | Every automated run uses `--factory-startup`. |
| B8 | `Event` has no `timer` attribute; a modal handler that reads it raises on the first timer tick. | The export modal handles any TIMER event and always ends the job (restoring context) on errors; the GUI check drives the real button path. |
| B9 | In Edit Mode, `Mesh.vertices`/weights are stale while evaluated copies already see the edit mesh. | `prepare()` flushes Edit Mode (ContextGuard) before measuring. |
| B10 | A local `copy()` of linked (library) data keeps the bare name; linked IDs cannot store properties. | Evaluation copies get throwaway names; linked objects export with a name-based id. |
| B11 | `hide_get()` on an object in an excluded collection returns False in 5.2.0 (no error), but `hide_set()` needs the object in the view layer. | ContextGuard only touches view-layer visibility for objects in the view layer. |
| B12 | Undo is unavailable in `--background`; memfile undo reloads data, so Python references taken before an undo are invalid. | Undo is verified in a short GUI session (`tests/blender_gui/gui_checks.py`). |

## Known limitations

- Materials: only slots (names and order) are reliable; FBX carries basic material data only. No material graph
  translation.
- Morph target *animation* curves are not exported (animation files contain the armature only).
- Skeletal-mesh sockets are not exported (static-mesh sockets only).
- Armature object motion is ignored unless the root-motion policy is "Object to Root".
- LODs are ignored for per-collection static assets and for skeletal assets with several render meshes.
- Unit-tested against the fake `unreal` module but **not acceptance-tested** in Unreal: *Import Materials*,
  *Import Textures*, *Build Nanite*, *Generate Lightmap UVs*, *Export Tangents*, and UE 5.7.
- Non-uniform armature scale cannot be baked exactly (warning).
- Generated LODs use Blender's Decimate (collapse); they are a starting point, not hand-authored LODs.
- The Unreal side is Python-only; "watched folder" and "remote command" import modes are not implemented.
- Unreal 5.7 and macOS/Linux have not been run through the acceptance gate.
