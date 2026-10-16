# Manifest and receipt formats

## Manifest (`unreal_export_manifest.json`), schema 1

```jsonc
{
  "schema": "blender-unreal-bridge/manifest",
  "schema_version": 1,
  "plan_id": "<sha256 of the canonical plan>",
  "plan_version": 1,
  "created_at": "2026-10-16T18:00:00Z",
  "generator": {"name": "unreal_exporter", "version": "0.1.0", "blender_version": "5.2.0 LTS"},
  "unreal_target": {"min": "5.6", "gate": "5.8"},
  "units": {"blender_unit_scale": 1.0, "fbx_units": "centimeter", "axis_forward": "-Z", "axis_up": "Y", ...},
  "settings": {"profile": "STATIC_MESH", "unreal_root": "/Game/BlenderExports", "origin_mode": "OBJECT", "fps": 30.0},
  "import_options": {
    "import_materials": false, "import_textures": false, "build_nanite": false, "generate_lightmap_uvs": false,
    "one_convex_hull_per_ucx": true, "create_physics_asset": true, "import_morph_targets": true,
    "normals": "import_normals", "vertex_colors": "replace", "import_lods": true, "import_sockets": true,
    "auto_generate_collision": true, "lod_collision_naming": "PER_ENGINE", "reimport_policy": "UPDATE_EXISTING"
  },
  "assets": [
    {
      "id": "<uuid of the root object / collection, or armature+action>",
      "kind": "STATIC_MESH | SKELETAL_MESH | ANIMATION",
      "asset_name": "SM_Crate",
      "unreal_path": "/Game/BlenderExports/SM_Crate",
      "destination_path": "/Game/BlenderExports",
      "file": "SM_Crate.fbx",                      // relative to the manifest, forward slashes
      "file_sha256": "…", "source_hash": "…",
      "file_variants": {"5.6": {"file": "SM_Crate.ue56.fbx", "file_sha256": "…"}},   // only when needed
      "status": "written | failed | skipped",
      "source": {"name": "SM_Crate", "collection": "Props", "objects": [...], "object_ids": [...], "sanitized_from": ""},
      "lods": [{"index": 1, "object": "SM_Crate_LOD1", "generated": true}],
      "lod_triangles": [1200, 600],
      "collisions": [{"object": "UCX_SM_Crate_00", "shape": "CONVEX", "index": 0}],
      "sockets": [{"name": "Lid", "object": "SOCKET_SM_Crate_Lid", "location_cm": [0, 0, 50],
                   "rotation": {"roll": 0, "pitch": 0, "yaw": -90}, "scale": [1, 1, 1]}],
      "material_slots": ["M_Wood"], "morph_targets": [], "triangles": 1200,
      "skeleton": {"armature": "Hero", "unreal_skeleton_path": "/Game/…/SK_Hero_Skeleton", "skeleton_asset_id": ""},
      "animation": {"action": "Walk", "frame_start": 1, "frame_end": 31, "fps": 30, "sample_step": 1.0,
                    "root_motion": "ROOT_BONE", "nla": "ACTION_ONLY", "expected_length_seconds": 1.0},
      "warnings": []
    }
  ]
}
```

Readers call `services.manifest.migrate()`: older versions are upgraded through the `MIGRATIONS` chain, newer
versions are refused with an "update the add-on" error, and a structural check rejects duplicate Unreal paths and
file paths that are absolute or contain `..`. The Unreal importer independently refuses unknown schema versions and
paths outside the manifest folder. Bump `MANIFEST_SCHEMA_VERSION` for any incompatible change and add a migration and
test for the previous version.

## Receipt (`unreal_import_receipt.json`), schema 1

Written by the importer beside the manifest:

```jsonc
{
  "schema": "blender-unreal-bridge/receipt", "schema_version": 1,
  "importer_version": "0.1.0", "engine_version": "5.8.3-…", "adapter": "5.8",
  "plan_id": "…", "started_at": "…", "finished_at": "…", "errors": [],
  "results": [
    {"asset_id": "…", "kind": "STATIC_MESH", "unreal_path": "/Game/…/SM_Crate",
     "status": "created | updated | failed | skipped", "objects": ["/Game/…/SM_Crate.SM_Crate"],
     "messages": ["added 1 socket(s) missing after FBX import"],
     "checks": {"collisions": {...}, "collisions_ok": true, "lods": 2, "lods_ok": true, "sockets_ok": 1, ...}}
  ]
}
```

Blender's *Load Import Receipt* button reads it and shows the Unreal status per asset.
