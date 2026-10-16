# ADR 0003: Temporary name journal for FBX node names

**Status:** accepted (2026-10-16)

**Context.** FBX node names come from Blender object names, which are unique per file, and Unreal identifies
collision, sockets, LODs and the dropped `Armature` node by name. Staged copies therefore need names that source
objects usually already hold (e.g. `SM_Crate`, `UCX_SM_Crate_00`, `Armature`). Alternatives considered: exporting
in a separate Blender process (slow, heavy), patching the exporter's naming (fragile), post-processing FBX binaries
(fragile).

**Decision.** `NameJournal.claim()` renames a conflicting *local* source datablock to `<name>.uexsrc###`, gives the
staged copy the wanted name, and `restore()` reverts every move in reverse order during cleanup. Source references
are resolved before the first claim.

**Consequences.** Names are restored after success, cancellation and forced failure (tests assert a deep fingerprint
of the scene). A crash of Blender itself mid-export would leave in-memory renames, but the operator runs inside one
call, so autosave cannot capture that state and the saved file is unaffected.
