# ADR 0005: Per-engine files for LOD assets with collision

**Status:** accepted (2026-10-16)

**Context.** Measured: with an FBX LOD group, Unreal 5.8 matches collision against the LOD-group name with the hull at
the root; Unreal 5.6 matches the LOD0 name and only cleanly when the hull is a child of LOD0. Any unmatched `UCX_`
mesh becomes render geometry (extra triangles and a `Material_0` slot); 5.6 also merges root-level hulls into LOD1+.
Writing both conventions into one file therefore corrupts LODs in at least one engine. 5.8 additionally drops
sockets on LOD-group assets.

**Decision.** Default `PER_ENGINE`: the main FBX uses the 5.8 layout; assets with both LODs and collision also get
`<name>.ue56.fbx` in the 5.6 layout, listed under `file_variants["5.6"]` in the manifest. The importer picks the
file by adapter. Sockets are reconciled from the manifest after import. Single-engine layouts remain selectable.

**Consequences.** Clean LODs and exact hull counts in both engines (acceptance fixture `SM_LodCombo`). Manual imports
on 5.6 must use the `.ue56.fbx` file.
