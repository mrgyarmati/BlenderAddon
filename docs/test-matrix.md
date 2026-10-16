# Test matrix

| Layer | Command | Runs where | Count |
|---|---|---|---|
| Unit | `py -3 -m unittest discover -s tests/unit -t .` | any CPython ≥ 3.13 (also Blender's bundled Python) | 144 |
| Blender integration | `py -3 scripts/run_blender_tests.py [--zip dist/…zip]` | Blender 5.2, `--background --factory-startup` | 52 |
| Install cycle | part of the release gate (`tests/blender_gui/enable_check.py`) | isolated `BLENDER_USER_RESOURCES` profile | install, enable/disable ×2, uninstall |
| GUI | part of the release gate (`tests/blender_gui/gui_checks.py`) | short Blender GUI session (undo and modal operators need a window) | 11 checks: undo/redo of 5 tools, Export button (modal) end to end, warning dialog |
| Unreal acceptance | `py -3 scripts/run_unreal_tests.py` | UnrealEditor-Cmd 5.8 and 5.6, `-run=pythonscript -NullRHI` | 95 checks per engine |
| Release gate | `py -3 scripts/verify_release.py [--skip-gui] [--skip-unreal]` | all of the above, plus build/validate/audit of the zip and tests against it | 10 gates |

## Unreal acceptance fixtures

Built by `scripts/make_fixture_files.py` (programmatically, so no binary fixtures live in the repo), exported with
the add-on into `build/acceptance/<run>/`, imported in Unreal by running each generated `import_to_unreal.py`, and
checked by `tests/unreal/acceptance.py`.

| Fixture | Assertions | 5.8.3 | 5.6.1 |
|---|---|---|---|
| Reference cube (`SM_RefCube`) | 100 cm size, +X facing marker at +X, Y mirrored, pivot at origin, one material slot | pass | pass |
| Door frame (`SM_DoorFrame`) | exactly 3 UCX hulls, hull bounds read, opening at (0,0,100) cm not covered | pass | pass |
| Socket prop (`SM_SocketProp`) | sockets `Top`/`Side` with expected location and rotation, box collision | pass | pass |
| Authored LODs (`SM_AuthoredLOD`) | 3 LODs, decreasing triangles, material order `M_A, M_B` | pass | pass |
| Auto LOD (`SM_AutoLOD`) | 3 LODs, ratios 0.5/0.25 within tolerance; Blender source unchanged | pass | pass |
| LOD + collision + socket (`SM_LodCombo`) | 2 LODs, exactly 1 hull, no stray geometry, socket present (5.8 via reconciliation) | pass | pass |
| Unicode / long names | `SM_Kiste_Gro_e_Unicode`; long name ≤ 64 chars with hash | pass | pass |
| Batch collections (`SM_BatchA/B`) | one asset per collection, correct helpers, no cross-asset socket/collision leakage | pass | pass |
| Skeletal character (`SK_Hero`) | bones `root, spine, head` (no `Armature` bone), bone scale 1, morph target `Bulge`, material slot | pass | pass |
| Animation (`A_Walk`, `A_Idle`) | skeleton target, length 1.0 s / 2.0 s, root motion enabled | pass | pass |
| Reimport | second import updates (no duplicates), editor-assigned material and socket preserved; renamed Blender source updates the original asset, no new asset | pass | pass |
| Automatic collision | `SM_RefCube` (no helpers) gets ≥ 1 hull; meshes with helpers get exactly their helpers | pass | pass |
| Skeletal LODs (`SK_HeroLod`) | 2 skeletal LODs, bones `root, spine` | pass | pass |
| Follow Rename | renamed Blender source renames the Unreal asset; exactly one static mesh remains | pass | pass |
| Plugin | `blender_bridge.import_manifest()` imports a manifest, versions match | pass | pass |

Results and logs: `build/acceptance_logs/ue_<version>_result.json` and `ue_<version>.log`.

`tests/unreal/introspect_api.py` dumps the Unreal Python API surface the importer relies on (run it in each
engine and diff the JSON) — use it first when adding support for a new Unreal version.

## Blender integration coverage

`tests/blender/`: registration cycles (twice, idempotent, nothing left behind); static export content (LOD groups,
per-engine collision layouts, sockets, centimetre bounds, pivots, world origin, modifiers, negative-scale winding,
multi-material slots, collection assets, centimetre scenes); skeletal (structure, bind pose round trip, morph
targets) and animation (manifest timing, key round trip, in-place, object-to-root, action-only); helper tools
(collision shapes, sockets in every placement mode, LOD generate/update/remove/assign/audit, authored LOD
protection, rename propagation, conflicts and swaps, duplicate id repair, fixes); robustness (deep source fingerprint
unchanged for every profile and after forced failures, cancellation, 40-asset scene, excluded/hidden collections,
Edit Mode flushing, linked library objects); every panel drawn through a validating fake layout.

## Unit coverage

`tests/unit/`: naming and path safety, discovery, validation catalogue, planning determinism, manifest round trip,
validation and migration, log redaction, Unreal rotation math (against measured UE values), importer logic against
a fake `unreal` module (adapters, explicit pipelines, sockets, checksums, variants, reimport policies, receipts,
generated script end to end), architecture rules (no bpy in pure layers, relative imports, reload order).
