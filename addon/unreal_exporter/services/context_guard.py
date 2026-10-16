"""Capture and restore user-visible Blender state around an operation.

Every operator that touches the scene runs inside :class:`ContextGuard`, which
restores mode, active object, selection, frame, active collection, visibility
flags and object transforms in ``__exit__`` -- including after exceptions.
"""

import bpy

_MODE_FOR_CONTEXT = {
    "EDIT_MESH": "EDIT",
    "EDIT_CURVE": "EDIT",
    "EDIT_SURFACE": "EDIT",
    "EDIT_TEXT": "EDIT",
    "EDIT_ARMATURE": "EDIT",
    "EDIT_METABALL": "EDIT",
    "EDIT_LATTICE": "EDIT",
    "EDIT_CURVES": "EDIT",
    "EDIT_POINT_CLOUD": "EDIT",
    "EDIT_GREASE_PENCIL": "EDIT",
    "POSE": "POSE",
    "SCULPT": "SCULPT",
    "PAINT_WEIGHT": "WEIGHT_PAINT",
    "PAINT_VERTEX": "VERTEX_PAINT",
    "PAINT_TEXTURE": "TEXTURE_PAINT",
    "PARTICLE": "PARTICLE_EDIT",
    "OBJECT": "OBJECT",
}


def _layer_collection_path(layer_collection, target, path=()):
    if layer_collection == target:
        return path + (layer_collection.name,)
    for child in layer_collection.children:
        found = _layer_collection_path(child, target, path + (layer_collection.name,))
        if found:
            return found
    return None


def _find_layer_collection(root, path):
    current = root
    for name in path[1:]:
        current = current.children.get(name)
        if current is None:
            return None
    return current


class ContextState:
    """Plain snapshot of restorable state (also used by tests to diff)."""

    def __init__(self, context):
        scene = context.scene
        view_layer = context.view_layer
        self.scene_name = scene.name
        self.view_layer_name = view_layer.name
        self.mode = _MODE_FOR_CONTEXT.get(context.mode, "OBJECT")
        active = view_layer.objects.active
        self.active = active.name if active else ""
        self.selected = sorted(ob.name for ob in view_layer.objects if ob.select_get(view_layer=view_layer))
        self.frame = (scene.frame_current, scene.frame_subframe)
        self.active_collection = _layer_collection_path(view_layer.layer_collection,
                                                        view_layer.active_layer_collection) or ()
        self.objects = {}
        in_layer = view_layer.objects
        for ob in scene.objects:
            # Objects in excluded collections are not in the view layer; hide_get() raises for them.
            hidden = ob.hide_get(view_layer=view_layer) if ob.name in in_layer else None
            self.objects[ob.name] = (
                ob.hide_viewport,
                hidden,
                ob.hide_select,
                ob.hide_render,
                tuple(tuple(row) for row in ob.matrix_basis),
            )
        self.names = sorted(ob.name for ob in bpy.data.objects)

    def diff(self, other) -> list:
        out = []
        for attr in ("scene_name", "view_layer_name", "mode", "active", "selected", "frame", "active_collection",
                     "names"):
            if getattr(self, attr) != getattr(other, attr):
                out.append("%s: %r != %r" % (attr, getattr(self, attr), getattr(other, attr)))
        for name, state in self.objects.items():
            if other.objects.get(name) != state:
                out.append("object %s: %r != %r" % (name, state, other.objects.get(name)))
        for name in other.objects:
            if name not in self.objects:
                out.append("object %s appeared" % name)
        return out


class ContextGuard:
    """Context manager restoring :class:`ContextState` on exit.

    ``object_mode=True`` switches to Object Mode on entry so edit-mode changes
    are flushed to mesh data before reading it.
    """

    def __init__(self, context, object_mode=True):
        self.context = context
        self.object_mode = object_mode
        self.state = None
        self.errors = []

    def __enter__(self):
        self.state = ContextState(self.context)
        if self.object_mode and self.state.mode != "OBJECT" and bpy.ops.object.mode_set.poll():
            bpy.ops.object.mode_set(mode="OBJECT")
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            self.restore()
        except Exception as error:  # never mask the original exception
            self.errors.append(str(error))
            if exc_type is None:
                raise
        return False

    def restore(self):
        state = self.state
        context = self.context
        scene = bpy.data.scenes.get(state.scene_name)
        if scene is None:
            return
        view_layer = scene.view_layers.get(state.view_layer_name)
        if context.window is not None and context.window.scene != scene:
            context.window.scene = scene
        if view_layer is None:
            return
        # Leave any mode we may have entered before touching selection.
        current_mode = _MODE_FOR_CONTEXT.get(context.mode, "OBJECT")
        if current_mode != "OBJECT" and bpy.ops.object.mode_set.poll():
            bpy.ops.object.mode_set(mode="OBJECT")

        if (scene.frame_current, scene.frame_subframe) != state.frame:
            scene.frame_set(state.frame[0], subframe=state.frame[1])

        objects = view_layer.objects
        for name, (hide_viewport, hidden, hide_select, hide_render, basis) in state.objects.items():
            ob = scene.objects.get(name)
            if ob is None:
                continue
            if ob.hide_viewport != hide_viewport:
                ob.hide_viewport = hide_viewport
            if hidden is not None and name in objects and ob.hide_get(view_layer=view_layer) != hidden:
                ob.hide_set(hidden, view_layer=view_layer)
            if ob.hide_select != hide_select:
                ob.hide_select = hide_select
            if ob.hide_render != hide_render:
                ob.hide_render = hide_render
            if tuple(tuple(row) for row in ob.matrix_basis) != basis:
                ob.matrix_basis = basis

        selected = set(state.selected)
        for ob in objects:
            want = ob.name in selected
            if ob.select_get(view_layer=view_layer) != want:
                try:
                    ob.select_set(want, view_layer=view_layer)
                except RuntimeError:
                    pass  # object hidden or not selectable in this view layer
        objects.active = objects.get(state.active) if state.active else None

        if state.active_collection:
            layer = _find_layer_collection(view_layer.layer_collection, state.active_collection)
            if layer is not None:
                view_layer.active_layer_collection = layer

        if state.mode != "OBJECT" and objects.active is not None and bpy.ops.object.mode_set.poll():
            try:
                bpy.ops.object.mode_set(mode=state.mode)
            except RuntimeError as error:
                self.errors.append("could not return to %s mode: %s" % (state.mode, error))
