# Unreal Export Bridge

A Blender 5.2 extension that prepares, validates and exports static meshes, skeletal meshes and animations to
Unreal Engine 5.6+ as FBX, together with a JSON manifest and a generated Unreal Python import script.

Verified with **Blender 5.2.0 LTS**, **Unreal Engine 5.8.3** (release gate) and **Unreal Engine 5.6.1**: the
acceptance suite imports a fixture set in both engines and passes all 95 checks in each (docs/test-matrix.md).

## Features

- Export selected objects, the active collection or chosen collections; one asset per object or per collection.
- Profiles: Static Mesh, Skeletal Mesh (optionally with its animations), Animation, Collection Scene.
- Collision helpers: box (`UBX_`), sphere (`USP_`), capsule (`UCP_`), convex hull and cylinder (`UCX_`), fitted to
  objects or to the edit-mode selection.
- Sockets at the 3D cursor, origin, selection median, active vertex/bone or from existing empties, with a preview of
  the Unreal-relative transform.
- LODs: authored meshes or non-destructive Decimate LODs from presets, triangle statistics and a side-by-side audit.
- Validation before export: names, transforms, UVs, topology, materials, rigs, weights, LOD chains, collision
  ownership, sockets, output paths. Blocking errors stop the export; safe fixes are offered with a preview.
- Batch rename that keeps every collision, socket and LOD attached to its asset.
- Animation: one action per file, explicit frame range and sampling, root-motion and NLA policies, baked through the
  rig's constraints.
- Never modifies the source scene: export works on temporary copies and restores selection, mode, frame and
  visibility afterwards.
- Unreal side: explicit Interchange pipelines, version adapters for 5.6 and 5.8, checksum verification, socket
  reconciliation, collision/LOD verification, reimport that updates the same assets (also after renaming in
  Blender), and a JSON import receipt.

## Install

1. Build the extension: `py -3 scripts/build_extension.py` (or `python3 …`), which writes
   `dist/unreal_exporter-0.1.0.zip`.
2. In Blender 5.2: *Edit → Preferences → Get Extensions → ⌄ → Install from Disk…* and pick the zip.
3. Open the 3D Viewport sidebar (N) → **Unreal Export**.

## Workflow

1. Select objects (or choose collections) and pick a profile.
2. Set the **Export Folder** (relative paths like `//unreal_export/` need a saved .blend) and the **Unreal Folder**
   (default `/Game/BlenderExports`).
3. Add collisions, sockets and LODs in the sub-panels as needed.
4. **Validate** and review the Validation panel; apply safe fixes or fix issues by hand.
5. **Export to Disk** or **Export + Script**. Progress shows in the status bar; Esc cancels after the current asset.
6. In Unreal 5.6+ (Python Editor Script Plugin enabled): *Tools → Execute Python Script…* and pick
   `import_to_unreal.py` from the export folder, or paste the command copied by **Copy Import Cmd** into the Python
   console. Alternatively install `unreal/BlenderBridge` as a project plugin and run
   `import blender_bridge; blender_bridge.import_manifest(r"…/unreal_export_manifest.json")`.
7. Back in Blender, **Load Import Receipt** shows what Unreal created or updated.

## Output

| File | Purpose |
|---|---|
| `<folder>/<Asset>.fbx` | one FBX per asset (centimetres, no node scale) |
| `<Asset>.ue56.fbx` | only for LOD assets with collision: the layout Unreal 5.6 needs (used automatically) |
| `unreal_export_manifest.json` | what was exported and how to import it (docs/manifest-schema.md) |
| `import_to_unreal.py` | standalone importer for Unreal 5.6+ |
| `unreal_export_log.txt` / `.jsonl` | export log (paths relative to the export folder) |
| `unreal_import_receipt.json` | written by Unreal after importing |

## Conventions

Helpers are named after their render mesh: `UCX_SM_Crate_00`, `SOCKET_SM_Crate_Lid`, `SM_Crate_LOD1`. Unreal asset
names are sanitized and prefixed (`SM_`, `SK_`, `A_`). Blender `(x, y, z)` metres become Unreal `(x, -y, z)`
centimetres; the asset pivot is the object origin. Details: docs/naming.md and docs/compatibility.md.

## Limitations

Material slots transfer, material graphs do not. Morph-target animation curves, skeletal-mesh sockets, Alembic/USD,
grooms, cameras, Control Rig and Sequencer workflows are out of scope. Unreal 5.7 and macOS/Linux have not been run
through the acceptance gate. See docs/compatibility.md.

## Development

See CLAUDE.md for commands, docs/architecture.md for the design, docs/test-matrix.md for coverage and
CONTRIBUTING.md for the clean-room rule. The full gate is `py -3 scripts/verify_release.py`.

## License

GPL-3.0-or-later (see LICENSE).
