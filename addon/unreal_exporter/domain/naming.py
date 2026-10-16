"""Naming rules: sanitization, helper naming conventions and path construction.

All functions are pure and deterministic. See docs/naming.md for the rules.
"""

from __future__ import annotations

import hashlib
import ntpath
import posixpath
import re
import unicodedata
from dataclasses import dataclass

from .. import constants as C

_INVALID_RUN = re.compile(r"[^A-Za-z0-9_]+")
_MULTI_UNDERSCORE = re.compile(r"_{2,}")
_LOD_SUFFIX = re.compile(r"^(?P<base>.+)_LOD(?P<index>\d+)$")
_COLLISION_INDEX = re.compile(r"^(?P<body>.+)_(?P<index>\d+)$")
_RESERVED_NAMES = frozenset({"none"})
_UNREAL_SEGMENT = re.compile(r"^[A-Za-z0-9_]+$")


class PathEscapeError(ValueError):
    """Raised when a relative output path would leave the export root."""


@dataclass(frozen=True)
class SanitizedName:
    value: str
    original: str

    @property
    def changed(self) -> bool:
        return self.value != self.original

    @property
    def valid(self) -> bool:
        return bool(self.value) and self.value.lower() not in _RESERVED_NAMES


def _ascii_fold(text: str) -> str:
    """Fold accented Latin characters to ASCII (é -> e); other characters are kept."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def sanitize_name(name: str, max_length: int = C.DEFAULT_MAX_NAME_LENGTH) -> SanitizedName:
    """Make ``name`` safe for Unreal asset names and file names.

    Rules: fold accents, replace every run of characters outside ``[A-Za-z0-9_]``
    with ``_``, collapse repeated underscores, strip leading/trailing underscores.
    Names longer than ``max_length`` are truncated and suffixed with a short hash
    of the original so distinct long names stay distinct.
    """
    original = name
    value = _ascii_fold(name or "")
    value = _INVALID_RUN.sub("_", value)
    value = _MULTI_UNDERSCORE.sub("_", value).strip("_")
    return SanitizedName(value=truncate_name(value, max_length, original), original=original)


def truncate_name(value: str, max_length: int, seed: str = None) -> str:
    """Shorten ``value`` to ``max_length`` with a hash of ``seed`` so long names stay distinct."""
    if not max_length or len(value) <= max_length:
        return value
    digest = hashlib.sha1((seed if seed is not None else value).encode("utf-8")).hexdigest()[:6]
    keep = max(1, max_length - len(digest) - 1)
    return value[:keep].rstrip("_") + "_" + digest


def apply_prefix(name: str, prefix: str) -> str:
    """Prefix ``name`` unless it already starts with ``prefix`` (case-insensitive)."""
    if not prefix:
        return name
    if name.lower().startswith(prefix.lower()):
        return name
    return prefix + name


# ---------------------------------------------------------------- helpers


def lod_object_name(base: str, index: int) -> str:
    return "%s%s%d" % (base, C.LOD_TOKEN, index)


def parse_lod_name(name: str):
    """Return ``(base, index)`` for names like ``SM_Crate_LOD2``, else ``None``."""
    match = _LOD_SUFFIX.match(name)
    if not match:
        return None
    return match.group("base"), int(match.group("index"))


def asset_base_name(object_name: str) -> str:
    """Object name without a trailing ``_LOD0`` (LOD0 roots name the asset)."""
    parsed = parse_lod_name(object_name)
    if parsed and parsed[1] == 0:
        return parsed[0]
    return object_name


def collision_object_name(shape: str, owner_name: str, index: int) -> str:
    prefix = C.COLLISION_PREFIXES[shape]
    return "%s%s_%02d" % (prefix, owner_name, index)


def parse_collision_name(name: str):
    """Return ``(shape, body, index)`` for ``UCX_Body_01`` style names, else ``None``.

    ``body`` is everything after the prefix with a trailing ``_NN`` removed, and
    ``index`` is ``None`` when the name has no numeric suffix (``UBX_Body``).
    """
    for prefix, shape in C.PREFIX_TO_SHAPE.items():
        if name.startswith(prefix) and len(name) > len(prefix):
            rest = name[len(prefix):]
            match = _COLLISION_INDEX.match(rest)
            if match:
                return shape, match.group("body"), int(match.group("index"))
            return shape, rest, None
    return None


def collision_matches_owner(name: str, owner_name: str) -> bool:
    """True when a collision helper name refers to exactly ``owner_name``.

    Both ``UCX_<Owner>_NN`` and the unnumbered ``UCX_<Owner>`` forms match; an
    owner whose own name ends in ``_NN`` is handled by the second comparison.
    """
    parsed = parse_collision_name(name)
    if parsed is None:
        return False
    shape, body, _index = parsed
    rest = name[len(C.COLLISION_PREFIXES[shape]):]
    return body == owner_name or rest == owner_name


def socket_object_name(owner_name: str, socket_name: str) -> str:
    return "%s%s_%s" % (C.SOCKET_PREFIX, owner_name, socket_name)


def parse_socket_name(name: str, owner_candidates) -> tuple | None:
    """Split ``SOCKET_<Owner>_<Socket>`` using the longest matching owner name.

    Returns ``(owner, socket)``; ``owner`` is ``""`` when no candidate matches, in
    which case the socket name is everything after the prefix.
    """
    if not name.startswith(C.SOCKET_PREFIX) or len(name) <= len(C.SOCKET_PREFIX):
        return None
    rest = name[len(C.SOCKET_PREFIX):]
    best = ""
    for owner in owner_candidates:
        if owner and rest.startswith(owner + "_") and len(rest) > len(owner) + 1 and len(owner) > len(best):
            best = owner
    if best:
        return best, rest[len(best) + 1:]
    return "", rest


def is_helper_name(name: str) -> bool:
    return name.startswith(C.SOCKET_PREFIX) or parse_collision_name(name) is not None


def unique_socket_name(existing: set, wanted: str) -> str:
    candidate = wanted
    counter = 1
    while candidate in existing:
        candidate = "%s_%d" % (wanted, counter)
        counter += 1
    return candidate


# ---------------------------------------------------------------- unreal paths


def normalize_unreal_root(root: str) -> str:
    root = (root or "").strip().replace("\\", "/")
    while "//" in root:
        root = root.replace("//", "/")
    if not root.startswith("/"):
        root = "/" + root
    return root.rstrip("/") or "/"


def validate_unreal_root(root: str) -> list:
    """Return a list of human-readable problems with an Unreal content root."""
    problems = []
    root = normalize_unreal_root(root)
    segments = [s for s in root.split("/") if s]
    if not segments:
        return ["Unreal root path is empty; use something like /Game/BlenderExports."]
    mount = segments[0]
    if mount in C.FORBIDDEN_MOUNT_POINTS:
        problems.append("Unreal mount point /%s is read-only or reserved; use /Game." % mount)
    for segment in segments:
        if not _UNREAL_SEGMENT.match(segment):
            problems.append("Unreal path segment '%s' may only contain letters, digits and underscores." % segment)
    return problems


def sanitize_folder(folder: str, max_length: int = C.DEFAULT_MAX_NAME_LENGTH) -> str:
    """Sanitize a relative folder override like ``Props/Kitchen`` segment by segment.

    ``..`` and empty segments are dropped, which also prevents escaping the root.
    """
    folder = (folder or "").replace("\\", "/")
    parts = []
    for raw in folder.split("/"):
        raw = raw.strip()
        if not raw or raw in (".", ".."):
            continue
        clean = sanitize_name(raw, max_length).value
        if clean:
            parts.append(clean)
    return "/".join(parts)


def build_unreal_path(root: str, folder: str, asset_name: str) -> str:
    """``("/Game/Exports", "Props", "SM_Crate")`` -> ``/Game/Exports/Props/SM_Crate``."""
    parts = [normalize_unreal_root(root).strip("/")]
    if folder:
        parts.append(folder.strip("/"))
    parts.append(asset_name)
    return "/" + "/".join(p for p in parts if p)


def split_unreal_path(path: str):
    """``/Game/A/B/SM_X`` -> ``("/Game/A/B", "SM_X")``."""
    head, _, tail = path.rpartition("/")
    return head or "/", tail


def file_relpath(folder: str, asset_name: str, extension: str = ".fbx") -> str:
    """Disk location of an asset relative to the export root (posix separators)."""
    if folder:
        return posixpath.join(folder, asset_name + extension)
    return asset_name + extension


# ---------------------------------------------------------------- filesystem


def _norm(path: str) -> str:
    return ntpath.normcase(ntpath.normpath(path)) if _looks_windows(path) else posixpath.normpath(path)


def _looks_windows(path: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", path)) or path.startswith("\\\\")


def is_within(root: str, path: str) -> bool:
    """True when ``path`` equals or is nested inside ``root`` (no symlink resolution)."""
    if not root or not path:
        return False
    if _looks_windows(root) != _looks_windows(path):
        return False
    root_n = _norm(root)
    path_n = _norm(path)
    sep = "\\" if _looks_windows(root) else "/"
    if path_n == root_n:
        return True
    return path_n.startswith(root_n.rstrip(sep) + sep)


def safe_join(root: str, relpath: str) -> str:
    """Join a posix ``relpath`` onto ``root``; raise :class:`PathEscapeError` if it escapes."""
    if not relpath or relpath.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", relpath):
        raise PathEscapeError("Output path '%s' must be relative to the export root." % relpath)
    parts = relpath.replace("\\", "/").split("/")
    if any(part in ("..", "") for part in parts):
        raise PathEscapeError("Output path '%s' contains '..' or empty segments." % relpath)
    if _looks_windows(root):
        joined = ntpath.normpath(ntpath.join(root, *parts))
    else:
        joined = posixpath.normpath(posixpath.join(root, *parts))
    if not is_within(root, joined):
        raise PathEscapeError("Output path '%s' resolves outside the export root." % relpath)
    return joined


def redact_path(path: str, root: str, debug: bool = False) -> str:
    """Express ``path`` relative to ``root`` for logs; absolute only in debug mode."""
    if debug or not path:
        return path
    if root and is_within(root, path):
        if _looks_windows(root):
            rel = ntpath.relpath(path, root)
            return rel.replace("\\", "/")
        return posixpath.relpath(path, root)
    return "<outside export root>/" + (ntpath.basename(path) if _looks_windows(path) else posixpath.basename(path))
