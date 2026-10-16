# Naming

## Unreal asset names

1. Start from the asset-name override, else the object name (a trailing `_LOD0` is removed), the collection name
   (per-collection assets) or the action name (animations; optionally `<Armature>_<Action>`).
2. Sanitize: fold accents (`é` → `e`), replace every run of characters outside `[A-Za-z0-9_]` with `_`, collapse
   repeated underscores, trim leading/trailing underscores. `Kiste_Größe_Ünïcödé` → `Kiste_Gro_e_Unicode`.
3. Prefix (when *Auto Prefix* is on and the name lacks it, case-insensitive): `SM_` static, `SK_` skeletal, `A_`
   animation.
4. Truncate to 64 characters (prefix included) as `<head>_<6 hex of sha1(original)>` so distinct long names stay
   distinct.

A name that is empty after sanitizing, or `None`, is a blocking error. Any change is reported as an info issue.

## Unreal paths and files

- Path: `<Unreal Folder>/<folder>/<AssetName>`; folder = per-object/collection override, or the collection hierarchy
  when *Collections as Folders* is on. Segments are sanitized; `..` is dropped.
- File: `<Export Folder>/<folder>/<AssetName>.fbx`; LOD assets with collision also get `<AssetName>.ue56.fbx`.
- Duplicate Unreal paths (case-insensitive) are blocking errors. Mount points `/Engine`, `/Script`, `/Temp`,
  `/Memory`, `/Config` are refused.
- Skeletons: `<SkeletalPath>_Skeleton` (Unreal's own naming) unless the armature has an *Unreal Skeleton* override.

## Helpers in Blender

| Helper | Blender name | Metadata (`object.uex`) |
|---|---|---|
| Box collision | `UBX_<Owner>_NN` | role COLLISION, shape BOX, owner id |
| Sphere collision | `USP_<Owner>_NN` | role COLLISION, shape SPHERE |
| Capsule collision | `UCP_<Owner>_NN` | role COLLISION, shape CAPSULE |
| Convex / cylinder | `UCX_<Owner>_NN` | role COLLISION, shape CONVEX |
| Socket | `SOCKET_<Owner>_<Socket>` (empty) | role SOCKET, socket name |
| LOD | `<Owner>_LOD<n>` (n ≥ 1; the owner is LOD0) | role LOD, index, generated flag |

`<Owner>` is the exact render-mesh object name. Helpers created by the add-on carry metadata (owner id), so they keep
belonging to their owner when renamed; helpers named by convention are recognised without metadata. A collision
whose name does not contain its owner's exact name is a **blocking error** (fix: *Rename helpers to match their
owner*). Collision indices `_NN` are kept when unique and renumbered otherwise.

## Names written to the FBX

The FBX does not reuse Blender names verbatim; staging writes Unreal-oriented names:

| Asset | FBX nodes |
|---|---|
| Static, no LODs | `<Asset>` mesh with children `UCX_<Asset>_NN`, `SOCKET_<Socket>` |
| Static with LODs (5.8 main file) | `<Asset>` LodGroup → `<Asset>_LOD0..n`; root-level `UCX_<Asset>_NN`; sockets under LOD0 |
| Static with LODs (`.ue56.fbx`) | same, but hulls are `UCX_<Asset>_LOD0_NN` under LOD0 |
| Per-collection static | one node per member (sanitized names), hulls `UCX_<Member>_NN` under their member |
| Skeletal | `Armature` (dropped by Unreal) → bones; skinned meshes at the root |
| Animation | `Armature` → bones, one take, keys from time 0 |

Unreal strips `SOCKET_`, so `SOCKET_SM_Crate_Lid` in Blender becomes the socket `Lid` in Unreal.

## Batch rename

Rename operates on asset roots (selected helpers resolve to their owner) with *Find & Replace*, *Prefix & Suffix* or
*Set Name*. Every helper follows: `UCX_<Old>_00` → `UCX_<New>_00`, `SOCKET_<Old>_Lid` → `SOCKET_<New>_Lid`,
`<Old>_LOD1` → `<New>_LOD1`. The preview lists conflicts (existing names, duplicates in the set, empty names); apply
refuses while conflicts remain and renames in two phases so swaps never collide. Export ids are unchanged, so a
re-export after renaming updates the same Unreal asset (see docs/architecture.md, "Reimport").
