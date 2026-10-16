# Claude Code Plan: Blender 5.2 to Unreal Engine 5.6–5.8 Add-on

## Project objective

Build a clean-room Blender extension that streamlines exporting static meshes, skeletal meshes, animations, custom collisions, sockets, and LODs to Unreal Engine. Public descriptions of the reference product include object and collection export, collision and socket creation, LOD creation/update/presets, animation export, batch renaming, disk/Unreal destinations, an edge-decal tool, and basic vehicle rigging.[^1][^2]

The primary supported environment is **Blender 5.2 LTS** and **Unreal Engine 5.6 or newer**, with **UE 5.8 as the release-gating target**. Blender 5.2 has current Python API documentation, and modern Blender add-ons should be packaged as extensions with `blender_manifest.toml` rather than relying only on legacy `bl_info` metadata.[^3][^4][^5]

This must be an independent implementation based only on documented workflows and public interoperability conventions. Do not copy, decompile, inspect, or imitate the reference product’s source code, private assets, wording, icons, or distinctive UI layout.

## Product boundaries

### MVP scope

- Export selected objects, active collection, or chosen collections.
- Export one asset per object or one asset per collection.
- Support static meshes, skeletal meshes, and one animation per output file.
- Create and manage box, capsule, sphere, cylinder/convex, and convex-hull collision helpers.
- Create sockets at the 3D cursor, selection center, active element, or from selected empties.
- Generate, update, remove, and preset LOD meshes.
- Validate transforms, names, UVs, mesh topology, armatures, actions, collision ownership, sockets, and LOD chains before export.
- Batch rename asset roots and all linked helpers safely.
- Export FBX files plus a machine-readable manifest.
- Generate an Unreal Python import script and optionally execute it through an explicit Unreal-side integration.
- Preserve the user’s selection, mode, frame, active object, visibility state, and object transforms after every operation.

### Deferred scope

- Edge decals and vehicle rigging.
- Alembic, USD, groom, camera, spline, Control Rig, Geometry Cache, and Sequencer workflows.
- Full Blender-material-to-Unreal-material graph translation.
- An always-on network bridge.
- Destructive automatic fixes without preview and confirmation.

Deferring these items keeps the first release focused on the workflows Unreal documents most clearly. FBX remains the recommended format for geometry, animation, and skeletal meshes, while Unreal’s FBX scene import supports static meshes, skeletal meshes, animations, materials, textures, morph targets, cameras, and lights with varying levels of fidelity.[^6][^7]

## Compatibility policy

| Component | Minimum | Release gate | Policy |
|---|---:|---:|---|
| Blender | 5.2.0 | Latest 5.2 LTS patch | Manifest sets `blender_version_min = "5.2.0"`; no compatibility shims for older Blender versions. |
| Unreal Engine | 5.6 | 5.8 latest patch | Import scripts use a small version adapter; CI/manual validation covers both 5.6 and 5.8. |
| Python in Blender | Bundled version | Blender 5.2 bundled version | No external runtime packages in MVP. |
| Platforms | Windows, macOS, Linux | Windows first, then all three | Core export must be platform-neutral; Unreal auto-import may initially be Windows-focused. |
| Export | FBX + JSON manifest | FBX imported in UE 5.8 | Do not promise interchangeability until the UE import test passes. |

Unreal 5.6 documentation states that its FBX pipeline uses FBX 2020.2 and warns that other exporter versions may cause incompatibilities. Blender exposes its FBX exporter through `bpy.ops.export_scene.fbx`, including controls for selection, active collection, unit scale, space conversion, mesh modifiers, custom properties, animation baking, texture paths, and forward/up axes. Therefore, the release gate must test the actual Blender-generated FBX files in UE 5.6 and UE 5.8 instead of assuming format compatibility from settings alone.[^8][^9][^10]

## User workflow

1. Select assets or collections in Blender.
2. Open **N-panel → Unreal Export**.
3. Choose an export profile: Static Mesh, Skeletal Mesh, Animation, or Collection Scene.
4. Add or inspect collisions, sockets, and LODs.
5. Run **Validate** and review errors, warnings, and safe fixes.
6. Choose **Export to Disk**, **Export + Generate Import Script**, or **Export + Import into Open Unreal Editor**.
7. Review a result panel containing output files, durations, warnings, and imported Unreal asset paths.

The reference workflow similarly centers on selecting objects, creating collisions/sockets/LODs, renaming related objects, and exporting objects or collections to Unreal, disk, or both. The new UI should reproduce the workflow’s utility, not its proprietary visual expression.[^11][^2]

## Unreal conventions

### Collisions

Use Unreal-recognized naming:

| Blender helper | Prefix | Constraint |
|---|---|---|
| Box | `UBX_` | Undeformed rectangular prism. |
| Capsule | `UCP_` | Capsule-shaped primitive. |
| Sphere | `USP_` | Sphere primitive. |
| Convex/cylinder approximation | `UCX_` | Closed convex mesh; multiple hulls use numbered suffixes. |

The helper name must contain the exact render-mesh name, for example `UCX_SM_Crate_00`, and the helper must be exported in the same FBX file as its render mesh. Unreal identifies collision from these prefixes, and its importer can either preserve one hull per UCX object or decompose it further.[^12][^13][^14]

Treat “cylinder collision” as a generated convex `UCX_` mesh, not as a separate Unreal prefix. Default to UCX for non-uniformly scaled or complex cases because Epic’s documented primitive caveats make spheres and boxes less reliable under non-uniform scaling.[^14]

### Sockets

Represent static-mesh sockets as empties named `SOCKET_<RenderMeshName>_<SocketName>` and parent them logically to the asset root. Unreal’s FBX pipeline recognizes dummy/helper objects with the `SOCKET_` prefix; public reference documentation also describes socket creation at the 3D cursor and prefix stripping on import.[^15][^14]

Add socket placement modes for 3D cursor, object origin, selection median, active vertex/bone, and existing empty. Socket transforms must be validated in the asset’s local coordinate system, with an export preview showing the expected Unreal-relative transform.

### LODs

Use sibling mesh objects with deterministic names such as `SM_Crate_LOD0`, `SM_Crate_LOD1`, and `SM_Crate_LOD2`. Unreal’s import options support mesh LOD import, and its Interchange configuration includes an `Import Lods` option when the source contains LODs.[^13][^12]

MVP LOD generation may use non-destructive Decimate modifiers, but the interface must clearly label this as automatic reduction and allow users to substitute authored meshes. Store presets as percentages or target triangle counts, never overwrite authored LODs without confirmation, and provide a visual side-by-side audit before export.

### Animation

Export each action as an individual FBX file by default, with explicit frame range, sample rate, root-motion policy, NLA policy, and skeleton reference. Epic’s FBX guidance recommends one animation per skeletal mesh per file, supports animation-only import when an existing skeleton is selected, and exposes frame-range and sample-rate settings.[^8][^12]

For skeletal meshes, validate a single export root, unique bone names, weighted vertices, consistent root bones across LODs, and the absence of unsupported duplicate bone names. These conditions correspond to documented Unreal FBX import failures.[^16]

## Export architecture

### Pipeline stages

1. **Discover** — Resolve selected objects/collections into `ExportAsset` records.
2. **Classify** — Determine static, skeletal, animation-only, helper, LOD, or unsupported type.
3. **Validate** — Run pure checks and produce structured `Issue` records.
4. **Plan** — Build an immutable `ExportPlan` containing dependencies, files, naming, transforms, and settings.
5. **Stage** — Duplicate required data into a temporary Blender collection or temporary scene.
6. **Normalize** — Apply export-only transforms, modifier evaluation, helper names, axes, and animation ranges to staged copies.
7. **Write** — Invoke Blender’s FBX exporter once per planned asset.
8. **Manifest** — Write JSON describing asset type, source UUID, source names, FBX path, Unreal destination, helpers, LODs, skeleton, action, settings, and content hash.
9. **Import** — Generate or invoke an Unreal Python importer.
10. **Restore/clean** — Remove staging data and restore the original context even after exceptions.
11. **Report** — Display structured results and persist a log beside the manifest.

Use a staging copy rather than mutating production objects. All operator entry points should call services that can be tested independently from Blender UI classes.

### Direct import modes

| Mode | Behavior | MVP status |
|---|---|---|
| Disk only | Writes FBX and JSON. User imports manually. | Required |
| Generated script | Writes `import_to_unreal.py` configured from the JSON manifest. | Required |
| Watched folder | Unreal-side plugin watches for completed manifests and imports them. | Later |
| Remote command | Blender sends a request to an explicitly enabled local Unreal endpoint. | Optional beta |

Unreal’s `AssetTools` API provides task-based and automated asset import capabilities, while the FBX import UI exposes static, skeletal, animation, physics, material, and naming controls. Keep Unreal-specific calls inside the generated importer/companion module so Blender-side export remains stable if Unreal’s Python API changes.[^17][^18]

The Unreal adapter should set import options explicitly rather than relying on editor defaults: destination path, static versus skeletal type, combine meshes, custom collision, LOD import, normal/tangent policy, materials/textures, skeleton target, morph targets, animations, physics asset, sample rate, and reimport policy. Unreal 5.6 documents these controls in both legacy FBX and Interchange pipelines.[^12][^13]

## Suggested repository

```text
blender-unreal-bridge/
├── CLAUDE.md
├── README.md
├── LICENSE
├── pyproject.toml
├── .gitignore
├── .claude/
│   ├── settings.json
│   ├── agents/
│   │   ├── blender-api-reviewer.md
│   │   ├── unreal-import-reviewer.md
│   │   └── test-reviewer.md
│   └── commands/
│       ├── implement-slice.md
│       ├── run-quality-gate.md
│       └── prepare-release.md
├── addon/
│   └── unreal_exporter/
│       ├── __init__.py
│       ├── blender_manifest.toml
│       ├── registration.py
│       ├── constants.py
│       ├── preferences.py
│       ├── properties.py
│       ├── operators/
│       │   ├── export.py
│       │   ├── validate.py
│       │   ├── collision.py
│       │   ├── socket.py
│       │   ├── lod.py
│       │   └── rename.py
│       ├── panels/
│       │   ├── main.py
│       │   ├── validation.py
│       │   └── results.py
│       ├── domain/
│       │   ├── models.py
│       │   ├── naming.py
│       │   ├── discovery.py
│       │   ├── validation.py
│       │   └── planning.py
│       ├── services/
│       │   ├── context_guard.py
│       │   ├── staging.py
│       │   ├── fbx_export.py
│       │   ├── collisions.py
│       │   ├── sockets.py
│       │   ├── lods.py
│       │   ├── animation.py
│       │   ├── manifest.py
│       │   └── logging.py
│       └── unreal_templates/
│           ├── importer_56.py.j2
│           └── importer_58.py.j2
├── unreal/
│   └── BlenderBridge/
│       ├── BlenderBridge.uplugin
│       └── Content/Python/
├── tests/
│   ├── unit/
│   ├── blender/
│   ├── fixtures/
│   └── unreal/
├── scripts/
│   ├── build_extension.py
│   ├── run_blender_tests.py
│   ├── make_fixture_files.py
│   └── verify_release.py
├── docs/
│   ├── architecture.md
│   ├── naming.md
│   ├── compatibility.md
│   └── test-matrix.md
└── dist/
```

Avoid Jinja2 in the packaged add-on unless it is vendored and justified; a standard-library template or data-driven Python generator is safer for MVP. The `.j2` names above describe logical templates and can be replaced with ordinary text templates.

## Core data model

Use dataclasses or immutable plain Python records in the domain layer:

```python
ExportAsset(
    id, source_object_ids, kind, asset_name, unreal_path,
    lods, collisions, sockets, armature_id, action_id, settings
)

ValidationIssue(
    code, severity, message, object_id, fix_id=None, details=None
)

ExportPlan(
    plan_version, blender_version, unreal_target,
    output_root, assets, files, import_options
)

ExportResult(
    plan_id, started_at, finished_at, files,
    warnings, failures, imported_assets
)
```

Assign a persistent UUID custom property to exportable Blender objects and collections. Names remain user-facing and may change; UUIDs let manifests and reimports map consistently without depending solely on mutable object names.

## Blender implementation rules

- Package as a Blender extension with `blender_manifest.toml`, `__init__.py`, explicit registration, and `blender_version_min = "5.2.0"`. Blender’s extension documentation defines this package shape and provides official build and validation commands.[^4][^19]
- Keep registration centralized and idempotent; unregister classes in reverse order.
- Use `PropertyGroup` objects for scene and object settings; use `AddonPreferences` only for machine-specific defaults.
- Keep UI drawing free of export logic.
- Minimize `bpy.ops` usage outside operators; prefer Blender data APIs where practical.
- Wrap unavoidable context-sensitive calls in tested context overrides.
- Never apply transforms or modifiers to source data during export.
- Use `try/finally` around staging, mode changes, temporary actions, and selection changes.
- Report actionable errors through both Blender’s operator report mechanism and structured logs.
- Do not perform background network activity unless the user explicitly enables it.

## Validation catalogue

### Blocking errors

- Duplicate planned Unreal asset paths.
- Invalid or empty asset name after sanitization.
- Missing mesh data or armature.
- Multiple candidate root armatures for one skeletal asset.
- Duplicate bone names or unweighted skeletal vertices.
- Animation-only export without a skeleton reference.
- LOD chain with missing LOD0, duplicate indices, or inconsistent skeleton root.
- Collision owner missing or name not exactly associated with the render mesh.
- Output outside the permitted project/export root.
- Export path is unwritable.

### Warnings

- Unapplied rotation or scale.
- Negative or non-uniform scale.
- Non-manifold geometry.
- Degenerate faces.
- Missing UV0 or overlapping lightmap UV channel.
- More material slots than expected.
- N-gons that will triangulate unpredictably.
- Socket outside a configurable distance from the asset bounds.
- LOD triangle count not decreasing.
- Very high bone influence count.
- Shape keys present but morph-target export disabled.
- Materials or textures requested despite FBX’s limited material translation; Unreal documents only basic FBX material support.[^9]

Safe fixes must be separate commands with preview. “Export anyway” may bypass warnings but never blocking errors unless a developer-mode override is enabled.

## Test strategy

### Unit tests

Run outside Blender where possible:

- Name sanitization and collision/socket/LOD naming.
- Asset discovery from mocked scene records.
- Validation rules.
- Plan determinism.
- Manifest serialization and schema migration.
- Path security and cross-platform path handling.
- Unreal importer generation for 5.6 and 5.8.

### Blender integration tests

Run Blender 5.2 in background mode with factory startup:

```bash
blender --background --factory-startup \
  --python-exit-code 1 \
  --python tests/blender/run_all.py
```

Blender officially supports background execution, running Python files, and nonzero exit codes on script failure; Blender’s own Python tests use the same headless pattern. Tests should install or load the packaged extension, register it, generate fixtures, invoke services/operators, inspect output, unregister it, and assert that the original scene context is unchanged.[^20][^21]

### Unreal acceptance tests

Create a small UE 5.6 project and a separate UE 5.8 project with editor scripting enabled. For every release candidate, import the exact files produced by Blender 5.2 and verify assets programmatically where possible, then visually inspect pivots, orientation, dimensions, normals, material slots, collisions, sockets, LOD switching, skeleton hierarchy, morph targets, and animation length.

| Fixture | Required assertions |
|---|---|
| Static cube | 100 cm reference size, correct +X facing, correct pivot, UV0, material slot. |
| Door frame | Three UCX hulls imported as collision with walkable opening. |
| Prop with sockets | Socket count, names, relative transforms, reimport stability. |
| Three authored LODs | LOD0–2 present, decreasing triangle counts, material order stable. |
| Auto LOD prop | Non-destructive source, expected reduction tolerance, no invalid topology. |
| Skeletal character | Bone hierarchy, weights, bind pose, material slots, optional morph target. |
| Animation-only | Correct skeleton target, frame range, duration, sample rate, root motion policy. |
| Batch collection | Deterministic files, no cross-asset helper leakage, unique UE paths. |
| Reimport | Same Unreal assets updated rather than duplicated; editor-authored settings preserved according to policy. |
| Unicode/long names | Predictable sanitization, clear warnings, valid files and UE asset names. |

Add a golden manifest for each fixture. Do not use binary FBX byte equality because exporter metadata can vary; compare semantic import results.

## Delivery phases

### Phase 0 — Specification

**Claude Code tasks**

- Create the repository, `CLAUDE.md`, architecture decision records, manifest schema, and test skeleton.
- Record supported versions, coordinate assumptions, naming rules, export profiles, reimport behavior, and out-of-scope features.
- Add a clean-room notice and contribution rule forbidding proprietary-source inspection.

**Exit criteria**

- Architecture, schema, naming, and compatibility documents are approved.
- A Blender 5.2 extension package builds and registers with an empty panel.
- Headless test command passes.

### Phase 1 — Static mesh export

**Claude Code tasks**

- Implement selection/collection discovery, naming, profiles, immutable plans, context guard, staging, and FBX writing.
- Add disk-only export, manifest generation, logs, and result UI.
- Build fixtures for pivots, multiple material slots, modifiers, UVs, and transforms.

**Exit criteria**

- Static mesh fixtures import correctly into UE 5.6 and 5.8.
- Source scenes remain byte-for-byte unchanged after save/reopen, except explicitly stored add-on properties.
- Exporting the same unchanged scene twice produces the same plan and semantic output.

### Phase 2 — Validation and collisions

**Claude Code tasks**

- Implement the validation framework and issue browser.
- Add box, sphere, capsule, and UCX hull creation in object and edit modes.
- Add ownership metadata, helper visibility controls, batch rename propagation, and one-hull-per-UCX setting.

**Exit criteria**

- Unreal imports every collision fixture with correct ownership and count.
- Helpers do not appear as render geometry.
- Invalid primitive deformation and non-convex UCX geometry are caught or clearly warned.

### Phase 3 — Sockets and LODs

**Claude Code tasks**

- Implement socket placement modes and transform preview.
- Implement authored LOD assignment and optional Decimate-based automatic LOD generation.
- Add LOD presets, triangle-budget display, update/remove operations, and export grouping.

**Exit criteria**

- Socket names/transforms and LOD chains survive initial import and reimport in UE 5.6 and 5.8.
- Generated LOD operations are non-destructive and undoable.

### Phase 4 — Skeletal and animation

**Claude Code tasks**

- Implement armature/mesh discovery, skeletal export profile, morph-target option, action picker, per-action export, NLA policy, root-motion policy, and frame/sample controls.
- Add validation for root bones, duplicate bones, weights, LOD skeleton compatibility, and animation-only skeleton references.

**Exit criteria**

- Character and animation fixtures import without FBX errors in both supported Unreal test projects.
- Animation length, frame range, sampling, and root behavior match the manifest.

### Phase 5 — Unreal automation

**Claude Code tasks**

- Generate versioned Unreal Python import scripts from manifests.
- Add 5.6 and 5.8 adapters and explicit import settings.
- Implement deterministic reimport mapping and structured import receipts.
- Optionally create a minimal Unreal companion plugin for a watched-folder or authenticated localhost endpoint.

**Exit criteria**

- A command imports all fixtures into a clean project without modal interaction.
- Import receipts list created/updated assets and failures.
- No hidden listener or remote-code execution exists unless explicitly enabled.

### Phase 6 — Release hardening

**Claude Code tasks**

- Add undo coverage, large-scene tests, cancellation, progress reporting, localization-ready strings, docs, sample files, migration tests, and changelog.
- Build and validate the official extension archive.
- Run the full compatibility matrix and package only files declared in the manifest.

**Exit criteria**

- `blender --command extension validate` passes for the source directory and final ZIP; Blender documents both validation and extension-building commands.[^22][^4]
- No critical or high-severity defects remain.
- UE 5.8 is a mandatory green gate; UE 5.6 is also green before claiming 5.6+ compatibility.

## Claude Code configuration

Claude Code reads project instructions from `CLAUDE.md` at session start, and project-level subagents can be placed in `.claude/agents/` with isolated contexts and restricted tools. Keep the root instructions compact because they remain in context throughout the session; put detailed Blender, Unreal, and testing rules in scoped files or subagents.[^23][^24][^25][^26]

### Recommended `CLAUDE.md`

```markdown
# Project mission
Build a clean-room Blender 5.2 extension for reliable Unreal Engine 5.6–5.8 asset export.
UE 5.8 is the release gate.

# Non-negotiable rules
- Never inspect or copy proprietary competitor code, assets, text, icons, or UI.
- Preserve source scenes; export through temporary staged copies.
- Prefer pure Python domain logic; isolate bpy and unreal API calls behind adapters.
- Do not add third-party runtime dependencies without approval.
- Do not claim compatibility until integration tests pass in the named versions.
- Every bug fix requires a regression test.
- Every operation must restore Blender context in try/finally.
- Do not silently rename, modify, delete, or overwrite user data.
- Keep files focused; avoid circular imports and giant operator modules.

# Commands
- Unit: python -m pytest tests/unit -q
- Blender: blender --background --factory-startup --python-exit-code 1 --python tests/blender/run_all.py
- Validate: blender --command extension validate addon/unreal_exporter
- Build: blender --command extension build --source-dir addon/unreal_exporter --output-dir dist
- Quality gate: python scripts/verify_release.py

# Workflow
1. Read the relevant architecture and compatibility docs.
2. Write or update failing tests first.
3. Implement the smallest vertical slice.
4. Run unit tests, Blender tests, extension validation, and static checks.
5. Update docs and changelog when behavior changes.
6. Report changed files, commands run, results, risks, and follow-ups.

# Definition of done
Code, tests, error handling, docs, and compatibility notes are complete; no placeholders or swallowed exceptions remain.
```

### Recommended subagents

| Agent | Permissions | Responsibility |
|---|---|---|
| `blender-api-reviewer` | Read-only | Check Blender 5.2 API use, registration, context safety, data ownership, undo behavior, and packaging. |
| `unreal-import-reviewer` | Read-only | Check FBX conventions and generated Unreal 5.6/5.8 importer code. |
| `test-reviewer` | Read-only plus test execution | Find missing edge cases, run focused tests, and verify acceptance criteria. |

Claude Code subagents are appropriate here because each specialist can inspect a noisy API surface or test log in its own context and return a concise review. Use hooks only for deterministic safeguards such as formatting changed Python files, blocking edits under `dist/`, and running a fast test subset; Claude Code hooks execute at lifecycle events and can enforce project rules without relying on model judgment.[^27][^26][^28][^29]

## Claude Code task protocol

Give Claude Code one vertical slice at a time. Each prompt should include the scope, source files, required tests, acceptance criteria, forbidden changes, and commands to run.

### Initial prompt

```text
Read CLAUDE.md and docs/architecture.md. Implement Phase 0 only.

Create a Blender 5.2 extension skeleton named unreal_exporter with a valid
blender_manifest.toml, centralized idempotent registration, an N-panel called
“Unreal Export,” and a headless smoke test that registers and unregisters the
extension twice.

Do not implement export features yet. Do not add third-party dependencies.
Use Blender 5.2 APIs only. Run the unit tests, Blender headless smoke test,
extension validation, and build command. Stop if Blender 5.2 is unavailable and
report the exact missing prerequisite rather than pretending tests passed.

Return: files changed, design decisions, commands and results, and remaining risks.
```

### Slice prompt template

```text
Implement [single feature] from Phase [N].

Required behavior:
- [observable behavior]
- [error behavior]
- [state-restoration behavior]

Tests first:
- [unit case]
- [Blender integration case]
- [UE acceptance fixture, if applicable]

Constraints:
- No unrelated refactors.
- No destructive changes to source objects.
- No new dependency.
- Keep Blender API calls behind the existing adapter/service boundary.
- Update docs and manifest schema only if behavior requires it.

Run the quality commands from CLAUDE.md. Do not mark the task complete unless all
available gates pass. Report skipped gates explicitly with a reason.
```

### Review prompt

```text
Review the current branch against the Phase [N] exit criteria. Delegate Blender
API, Unreal import, and test coverage reviews to the configured read-only
subagents. Fix only confirmed issues, add regression tests, and rerun the full
quality gate. Produce a pass/fail checklist with evidence from test output.
```

## Release checklist

- Extension installs, enables, disables, and uninstalls cleanly in Blender 5.2.
- Register/unregister cycles leave no classes, handlers, properties, timers, or keymaps behind.
- Static, skeletal, animation-only, collision, socket, LOD, batch, and reimport fixtures pass.
- Blender context and source data remain intact after success, cancellation, and forced failure.
- Import scripts pass in clean UE 5.6 and 5.8 projects.
- 5.8 test evidence is attached to the release artifact.
- Manifest schema is versioned and backward migration is tested.
- Logs omit secrets and avoid absolute local paths unless debug mode is enabled.
- Network features are disabled by default and bound only to localhost when enabled.
- Extension ZIP validates and contains no test fixtures, caches, credentials, or generated project files.
- Documentation explains axis/scale assumptions, collision/socket/LOD naming, animation policy, reimport behavior, and known limitations.

## Success criteria

Version 1.0 is successful when an artist can prepare a representative static or skeletal asset in Blender 5.2, detect pipeline problems before export, produce deterministic FBX/manifest outputs, and import or reimport the asset into UE 5.8 with correct scale, orientation, pivot, materials slots, collisions, sockets, LODs, skeleton, and animation—without modifying the source scene or requiring manual cleanup. UE 5.6 must pass the same baseline fixtures before the product advertises “5.6+” support.

---

## References

1. [Blender to Unreal - GitHub Pages](https://b3dhub.github.io/blender-to-unreal-docs/) - Create, Update, and Preset LODs of the selected objects.

2. [Blender to Unreal - Blender Addon - GitHub Pages](https://b3dhub.github.io/addons/blender-to-unreal) - Blender-to-Unreal is a Blender addon that exports objects, animations, collisions, sockets, and LODs...

3. [Blender Python API](https://docs.blender.org/api/current/index.html) - Welcome to the Python API documentation for , the free and open source 3D creation suite.

4. [How to Create Extensions - Blender 5.2 LTS Manual](https://docs.blender.org/manual/en/latest/advanced/extensions/getting_started.html) - A manifest is a file with all the meta-data required for an extension to be processed.

5. [API Overview - Blender Python API](https://docs.blender.org/api/current/info_overview.html) - The only difference between add-on extensions and built-in Python modules is that add-ons must inclu...

6. [Importing Content into Unreal Engine from Maya | Unreal Engine 5.6 Documentation | Epic Developer Community](https://dev.epicgames.com/documentation/en-us/unreal-engine/importing-content-into-unreal-engine-from-maya) - |**FBX **|`.fbx`|The recommended format for geometry, animations, and skeletal meshes.|

7. [FBX Scene Import in Unreal Engine | Unreal Engine 5.6 Documentation | Epic Developer Community](https://dev.epicgames.com/documentation/en-us/unreal-engine/fbx-scene-import-in-unreal-engine) - 4. Using the FBX Scene Import Dialog, select the assets (static meshes, skeletal meshes, and materia...

8. [Importing Animations Using FBX in Unreal Engine | Unreal Engine 5.6 Documentation | Epic Developer Community](https://dev.epicgames.com/documentation/en-us/unreal-engine/importing-animations-using-fbx-in-unreal-engine) - 3. Click **Open** to begin importing the FBX file you want to import to your project.

9. [Importing Materials Reference in Unreal Engine | Unreal Engine 5.6 Documentation | Epic Developer Community](https://dev.epicgames.com/documentation/en-us/unreal-engine/importing-materials-reference-in-unreal-engine) - The Unreal Engine FBX import pipeline uses **FBX 2020.2**.

10. [Export Scene Operators - Blender Python API](https://docs.blender.org/api/current/bpy.ops.export_scene.html) - **bpy.ops.export_scene.fbx(***, *filepath=''*, *check_existing=True*, *filter_glob='*.fbx'*, *use_se...

11. [Blender to Unreal - karan@b3dhub](https://b3dhub.gumroad.com/l/blender-to-unreal) - Create Sockets for the selected object(s).
Create LODs for the selected object(s).

12. [FBX Import Options Reference in Unreal Engine | Unreal Engine 5.6 Documentation | Epic Developer Community](https://dev.epicgames.com/documentation/en-us/unreal-engine/fbx-import-options-reference-in-unreal-engine) - When you import content through the **Content Browser** using the FBX pipeline, the **FBX Import Opt...

13. [Interchange Import Reference in Unreal Engine | Unreal Engine 5.6 Documentation | Epic Developer Community](https://dev.epicgames.com/documentation/en-us/unreal-engine/interchange-import-reference-in-unreal-engine) - |**Convert Statics with Morph Targets to Skeletals**|Converts static meshes using morph targets to s...

14. [FBX Static Mesh Pipeline | Unreal Engine 4.27 Documentation | Epic Developer Community](https://dev.epicgames.com/documentation/en-us/unreal-engine/fbx-static-mesh-pipeline?application_version=4.27) - |**UCX_[RenderMeshName]_##**|A **Convex** object can be any completely closed convex 3D shape.

15. [# Socket](https://b3dhub.github.io/blender-to-unreal-docs/socket.html) - `SOCKET_socket`in Blender becomes
`socket`in Unreal.

16. [FBX Import Errors in Unreal Engine | Unreal Engine 5.6 Documentation | Epic Developer Community](https://dev.epicgames.com/documentation/en-us/unreal-engine/fbx-import-errors-in-unreal-engine) - This error is thrown when importing an LOD (or importing a Skeletal Mesh with LODs) and the requeste...

17. [unreal.AssetTools¶](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/AssetTools?application_version=5.2) - - **Parameters:** **import_tasks** (*[* *]*) – Tasks that specify how to import each file - **import...

18. [unreal.FbxImportUI¶](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/FbxImportUI?application_version=5.2) - By default, it will be the name of FBX * - `override_full_name` (bool): [Read-Write] Use the string ...

19. [Extensions Command Line Arguments](https://docs.blender.org/manual/en/latest/advanced/command_line/extension_arguments.html) - blender --command extension build [-h] [--source-dir SOURCE_DIR]

20. [Python Tests¶](https://developer.blender.org/docs/handbook/testing/python/) - `./blender.bin --background --python tests/python/bl_pyapi_mathutils.py -- --verbose`

21. [Command Line Arguments - Blender 5.2 LTS Manual](https://docs.blender.org/manual/en/latest/advanced/command_line/arguments.html) - - **`-P`, `--python` `<filepath>`**
  Run the given Python script file.

22. [How to Create Extensions#](https://docs.blender.org/manual/ja/4.2/advanced/extensions/getting_started.html) - blender --command extension build
...
blender --command extension validate
...
blender --command ext...

23. [code.claude.com › docs › enExplore the .claude directory - Claude Code Docs](https://code.claude.com/docs/en/claude-directory) - > Where Claude Code reads CLAUDE.md, settings.json, hooks, skills, commands, subagents, workflows, r...

24. [Steering Claude Code: when to use CLAUDE.md, skills, hooks ...](https://claude.com/resources/articles/steering-claude-code-skills-hooks-rules-subagents-and-more) - It loads into context at session start and stays there for the entire session.

25. [When Claude Code reads...](https://code.claude.com/docs/en/memory) - CLAUDE.md files are markdown files that give Claude persistent instructions for a project, your pers...

26. [code.claude.com › docs › enCreate custom subagents - Claude Code Docs](https://code.claude.com/docs/en/sub-agents) - Subagents are specialized AI assistants that handle specific types of tasks.
...
Each subagent runs ...

27. [Resume subagents](https://code.claude.com/docs/en/agent-sdk/subagents) - Subagents are separate agent instances that your main agent can spawn to handle focused subtasks.

28. [Hooks reference - Claude Code Docs](https://code.claude.com/docs/en/hooks) - Hooks are user-defined shell commands, HTTP endpoints, MCP tool calls, LLM prompts, or subagents tha...

29. [Automate actions with hooks - Claude Code Docs](https://code.claude.com/docs/en/hooks-guide) - Hooks are user-defined shell commands.
Claude Code runs them at specific points in its lifecycle, wh...

