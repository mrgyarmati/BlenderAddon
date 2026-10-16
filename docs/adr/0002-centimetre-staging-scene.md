# ADR 0002: Stage copies in a temporary centimetre scene

**Status:** accepted (2026-10-16)

**Context.** The plan requires that source scenes never change. Blender's default FBX export of metre scenes puts a
×100 scale on FBX root nodes; Unreal 5.6.1 and 5.8.3 then import every bone and socket with scale 100
(`FBX_SCALE_NONE` and `FBX_SCALE_ALL` alike). Hidden objects are not evaluated by Blender.

**Decision.** For each asset create a temporary scene with unit scale 0.01, build evaluated copies of the sources
(through visible evaluation copies) transformed into centimetres around the asset pivot, and export that scene's
export collection with `temp_override(scene=…)` and `collection=…`. Remove every temporary datablock in `finally`.

**Consequences.** Unreal sees unit-scale skeletons and sockets with correct sizes; the user's scene, selection, frame
and visibility are untouched; transforms and modifiers are baked into the exported copy. Costs one extra copy per
source object per export.
