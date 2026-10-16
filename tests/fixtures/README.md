# Fixtures

Test scenes are built programmatically so no binary `.blend`/`.fbx` files live in the repository:

- `tests/blender/fixtures.py`: small builders (cubes with materials and UVs, collections, a two-bone rig with a
  skinned mesh, an optional shape key and a keyed action) used by the Blender integration tests.
- `scripts/make_fixture_files.py`: the Unreal acceptance fixture set (reference cube, door frame, socket prop,
  authored/auto/combined LODs, unicode and long names, batch collections, skeletal character with animations,
  rename-then-reimport). It writes the exports, `expectations.json` and a `fixtures.blend` for inspection into
  `build/acceptance/` (git-ignored).
