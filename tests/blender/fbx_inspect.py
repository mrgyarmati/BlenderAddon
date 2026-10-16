"""Read back exported FBX files with Blender's bundled parser (io_scene_fbx.parse_fbx)."""

from io_scene_fbx import parse_fbx


def _name(elem):
    return elem.props[1].split(b"\x00\x01")[0].decode("utf-8")


def _props70(elem):
    out = {}
    for child in elem.elems:
        if child.id != b"Properties70":
            continue
        for p in child.elems:
            key = p.props[0].decode("utf-8")
            out[key] = p.props[4:]
    return out


class FbxFile:
    def __init__(self, path):
        root, _version = parse_fbx.parse(path)
        self.models = {}  # name -> dict(type, uid, props)
        self.attributes = {}  # node attribute name -> type
        self.geometries = {}  # uid -> dict(name, vertices, polygons)
        self.unit_scale = None
        self.anim_stacks = []
        self._by_uid = {}
        connections = []
        for elem in root.elems:
            if elem.id == b"GlobalSettings":
                props = _props70(elem)
                if "UnitScaleFactor" in props:
                    self.unit_scale = float(props["UnitScaleFactor"][0])
            if elem.id == b"Objects":
                for obj in elem.elems:
                    uid = obj.props[0]
                    if obj.id == b"Model":
                        name = _name(obj)
                        self.models[name] = {"type": obj.props[2].decode(), "uid": uid, "props": _props70(obj),
                                             "parent": None, "geometry": None}
                        self._by_uid[uid] = ("model", name)
                    elif obj.id == b"NodeAttribute":
                        self.attributes[_name(obj)] = obj.props[2].decode()
                    elif obj.id == b"Geometry":
                        data = {"name": _name(obj), "vertices": [], "polygons": [], "materials": []}
                        for child in obj.elems:
                            if child.id == b"LayerElementMaterial":
                                for sub in child.elems:
                                    if sub.id == b"Materials":
                                        data["materials"] = list(sub.props[0])
                            if child.id == b"Vertices":
                                values = list(child.props[0])
                                data["vertices"] = [tuple(values[i:i + 3]) for i in range(0, len(values), 3)]
                            elif child.id == b"PolygonVertexIndex":
                                poly = []
                                for index in child.props[0]:
                                    if index < 0:
                                        poly.append(-index - 1)
                                        data["polygons"].append(poly)
                                        poly = []
                                    else:
                                        poly.append(index)
                        self.geometries[uid] = data
                        self._by_uid[uid] = ("geometry", uid)
                    elif obj.id == b"AnimationStack":
                        self.anim_stacks.append({"name": _name(obj), "props": _props70(obj)})
            if elem.id == b"Connections":
                for c in elem.elems:
                    if c.props[0] == b"OO":
                        connections.append((c.props[1], c.props[2]))
        for child_uid, parent_uid in connections:
            child = self._by_uid.get(child_uid)
            parent = self._by_uid.get(parent_uid)
            if child is None or parent is None:
                continue  # scene root (uid 0) or non-model links such as bone -> skin cluster
            if child[0] == "model" and parent[0] == "model":
                self.models[child[1]]["parent"] = parent[1]
            elif child[0] == "geometry" and parent[0] == "model":
                self.models[parent[1]]["geometry"] = child[1]

    def children(self, name):
        return sorted(n for n, m in self.models.items() if m["parent"] == name)

    def roots(self):
        return sorted(n for n, m in self.models.items() if m["parent"] is None)

    def geometry(self, model_name):
        uid = self.models[model_name]["geometry"]
        return self.geometries[uid] if uid is not None else None

    def bounds(self, model_name):
        verts = self.geometry(model_name)["vertices"]
        lo = tuple(min(v[i] for v in verts) for i in range(3))
        hi = tuple(max(v[i] for v in verts) for i in range(3))
        return lo, hi

    def signed_volume(self, model_name):
        """Positive for closed meshes with outward-facing (CCW) winding."""
        geo = self.geometry(model_name)
        verts = geo["vertices"]
        volume = 0.0
        for poly in geo["polygons"]:
            a = verts[poly[0]]
            for i in range(1, len(poly) - 1):
                b = verts[poly[i]]
                c = verts[poly[i + 1]]
                volume += (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0])
                           + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6.0
        return volume

    def translation(self, model_name):
        value = self.models[model_name]["props"].get("Lcl Translation")
        return tuple(float(v) for v in value) if value else (0.0, 0.0, 0.0)
