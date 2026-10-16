# ADR 0004: Configure Interchange pipelines explicitly in the importer

**Status:** accepted (2026-10-16)

**Context.** Unreal 5.6 and 5.8 route FBX through Interchange. Passing legacy `FbxImportUI` options converts them
and ties custom-collision import to auto-generated collision. Property names differ between 5.6 and 5.8, and 5.8
rejects some deprecated properties.

**Decision.** The importer builds an `InterchangeGenericAssetsPipeline`, sets every relevant option explicitly, and
passes it through `InterchangePipelineStackOverride` on an automated, synchronous `AssetImportTask`. Version
differences live in `Adapter56`/`Adapter58`, selected from the running engine version. The importer is one
standard-library module embedded into each generated script and shipped in the optional plugin.

**Consequences.** Imports do not depend on editor defaults or project settings; adding a new engine means adding an
adapter and running the acceptance gate.
