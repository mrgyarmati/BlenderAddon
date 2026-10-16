"""Blender -> Unreal transform conversion (pure Python, no mathutils).

With the exporter's default axes (forward -Z, up Y) Unreal imports Blender
``(x, y, z)`` metres as ``(x, -y, z)`` centimetres: the Y axis is mirrored to
switch handedness. Rotations are conjugated by that mirror. Verified against
UE 5.6.1 and 5.8.3 imports; see docs/compatibility.md.
"""

from __future__ import annotations

import math

_MIRROR = (1.0, -1.0, 1.0)


def location_to_unreal(location, cm_per_unit: float) -> tuple:
    x, y, z = location
    return (x * cm_per_unit, -y * cm_per_unit, z * cm_per_unit)


def rotation_to_unreal_matrix(m3) -> tuple:
    """Conjugate a 3x3 rotation (rows of a column-vector matrix) by the Y mirror."""
    return tuple(tuple(_MIRROR[i] * _MIRROR[j] * m3[i][j] for j in range(3)) for i in range(3))


def matrix_to_quaternion(m3) -> tuple:
    """Unit quaternion ``(x, y, z, w)`` of an orthonormal 3x3 matrix."""
    m00, m01, m02 = m3[0]
    m10, m11, m12 = m3[1]
    m20, m21, m22 = m3[2]
    trace = m00 + m11 + m22
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * s
        x = (m21 - m12) / s
        y = (m02 - m20) / s
        z = (m10 - m01) / s
    elif m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2.0
        w = (m21 - m12) / s
        x = 0.25 * s
        y = (m01 + m10) / s
        z = (m02 + m20) / s
    elif m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2.0
        w = (m02 - m20) / s
        x = (m01 + m10) / s
        y = 0.25 * s
        z = (m12 + m21) / s
    else:
        s = math.sqrt(1.0 + m22 - m00 - m11) * 2.0
        w = (m10 - m01) / s
        x = (m02 + m20) / s
        y = (m12 + m21) / s
        z = 0.25 * s
    norm = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    return (x / norm, y / norm, z / norm, w / norm)


def _normalize_axis(angle: float) -> float:
    angle = math.fmod(angle, 360.0)
    if angle > 180.0:
        angle -= 360.0
    elif angle <= -180.0:
        angle += 360.0
    return angle


def quaternion_to_rotator(q) -> tuple:
    """Unreal ``FQuat::Rotator`` semantics. Returns ``(roll, pitch, yaw)`` in degrees."""
    x, y, z, w = q
    singularity = z * x - w * y
    yaw_y = 2.0 * (w * z + x * y)
    yaw_x = 1.0 - 2.0 * (y * y + z * z)
    threshold = 0.4999995
    rad = 180.0 / math.pi
    if singularity < -threshold:
        pitch = -90.0
        yaw = math.atan2(yaw_y, yaw_x) * rad
        roll = _normalize_axis(-yaw - 2.0 * math.atan2(x, w) * rad)
    elif singularity > threshold:
        pitch = 90.0
        yaw = math.atan2(yaw_y, yaw_x) * rad
        roll = _normalize_axis(yaw - 2.0 * math.atan2(x, w) * rad)
    else:
        pitch = math.asin(max(-1.0, min(1.0, 2.0 * singularity))) * rad
        yaw = math.atan2(yaw_y, yaw_x) * rad
        roll = math.atan2(-2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y)) * rad
    return (_clean(roll), _clean(pitch), _clean(yaw))


def rotator_to_matrix(roll: float, pitch: float, yaw: float) -> tuple:
    """Unreal ``FRotationMatrix`` as a column-vector 3x3 matrix (rows)."""
    sr, cr = math.sin(math.radians(roll)), math.cos(math.radians(roll))
    sp, cp = math.sin(math.radians(pitch)), math.cos(math.radians(pitch))
    sy, cy = math.sin(math.radians(yaw)), math.cos(math.radians(yaw))
    # Unreal's FRotationMatrix rows are the rotated basis axes (row-vector form);
    # transpose to get the column-vector matrix used elsewhere in this module.
    x_axis = (cp * cy, cp * sy, sp)
    y_axis = (sr * sp * cy - cr * sy, sr * sp * sy + cr * cy, -sr * cp)
    z_axis = (-(cr * sp * cy + sr * sy), cy * sr - cr * sp * sy, cr * cp)
    return tuple(tuple((x_axis, y_axis, z_axis)[j][i] for j in range(3)) for i in range(3))


def rotation_to_unreal_rotator(m3) -> tuple:
    """Blender 3x3 rotation -> Unreal ``(roll, pitch, yaw)`` degrees."""
    return quaternion_to_rotator(matrix_to_quaternion(rotation_to_unreal_matrix(m3)))


def matrices_close(a, b, tolerance: float = 1e-4) -> bool:
    return all(abs(a[i][j] - b[i][j]) <= tolerance for i in range(3) for j in range(3))


def decompose(m4) -> tuple:
    """Split a row-major 4x4 (column-vector) matrix into (location, rotation3x3, scale)."""
    cols = [[m4[r][c] for r in range(3)] for c in range(3)]
    scale = [math.sqrt(sum(v * v for v in col)) for col in cols]
    det = (
        m4[0][0] * (m4[1][1] * m4[2][2] - m4[1][2] * m4[2][1])
        - m4[0][1] * (m4[1][0] * m4[2][2] - m4[1][2] * m4[2][0])
        + m4[0][2] * (m4[1][0] * m4[2][1] - m4[1][1] * m4[2][0])
    )
    if det < 0:
        scale[0] = -scale[0]
    rot = tuple(tuple((cols[c][r] / scale[c]) if scale[c] else 0.0 for c in range(3)) for r in range(3))
    location = (m4[0][3], m4[1][3], m4[2][3])
    return location, rot, tuple(scale)


def _clean(value: float) -> float:
    value = round(value, 6)
    return 0.0 if value == 0.0 else value
