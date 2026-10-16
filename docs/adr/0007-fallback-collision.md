# ADR 0007: Automatic collision only for meshes without helpers

**Status:** accepted (2026-10-16)

**Context.** Unreal's own FBX import gives a static mesh simple collision when the file has none. Disabling the
fallback for every asset left helper-less meshes without any collision, which surprises users; enabling it blindly
could add an automatic hull next to authored `UCX_` hulls.

**Decision.** A scene setting *Collision When Missing* (default on) is written to the manifest. The importer sets
`fallback_collision_type = CONVEX18DOP` only for static meshes whose manifest lists no collision helpers and `NONE`
otherwise. Verification accepts "at least one hull" for helper-less meshes and exact counts for the rest.

**Consequences.** Helper-less meshes behave like Unreal's default import; meshes with helpers get exactly their
helpers (acceptance: `SM_RefCube` ≥ 1 hull, `SM_DoorFrame` exactly 3).
