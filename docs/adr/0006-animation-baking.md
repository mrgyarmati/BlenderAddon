# ADR 0006: Bake animation from an evaluation copy of the rig

**Status:** accepted (2026-10-16)

**Context.** Exported animation must honour constraints, IK and drivers, export one action per file, support NLA and
root-motion policies, and must not change the user's frame, action assignment or NLA. The staged armature is scaled
to centimetres, so the source action's curves cannot be reused directly.

**Decision.** Copy the source armature object into the staging scene (self-references in drivers/constraints remapped
to the copy), assign the chosen action with NLA muted (or keep the scene result), sample armature-space bone matrices
per frame, map them into staged space (per frame for "Object to Root"), apply the root-motion policy, convert to
local keys under full inheritance and write them to a new slotted action on the staged armature. Keys start at FBX
time 0.

**Consequences.** Exported motion matches what the rig evaluates to in Blender (verified by re-importing the FBX and
by Unreal length/root-motion checks). Sampling costs one depsgraph evaluation per frame.
