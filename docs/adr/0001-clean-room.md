# ADR 0001: Clean-room implementation

**Status:** accepted (2026-10-16)

**Context.** The feature set is modelled on publicly described workflows of an existing commercial add-on.

**Decision.** Build only from public documentation of that workflow, Blender's and Unreal's APIs and our own
measurements. Never inspect or copy the reference product's code, assets, text, icons or UI layout
(CONTRIBUTING.md). Interoperability facts are recorded as measurements in docs/compatibility.md.

**Consequences.** Every non-obvious behaviour is backed by a probe or acceptance test instead of borrowed code.
