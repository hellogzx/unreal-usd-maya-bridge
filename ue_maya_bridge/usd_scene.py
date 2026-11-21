"""Read USD geometry with the host's own pxr modules (no external USD install)."""

import hashlib
import json
from pathlib import Path


def inspect_stage(path):
    """Inspect composed meshes, including instance proxies, at default time."""
    from pxr import Usd, UsdGeom, Gf

    stage = Usd.Stage.Open(str(Path(path).resolve()))
    if stage is None:
        raise ValueError("Cannot open USD stage: " + str(path))
    result = {
        "up_axis": str(UsdGeom.GetStageUpAxis(stage)),
        "meters_per_unit": UsdGeom.GetStageMetersPerUnit(stage),
        "meshes": [],
    }
    cache = UsdGeom.XformCache()
    for prim in Usd.PrimRange.Stage(stage, Usd.TraverseInstanceProxies()):
        if not prim.IsA(UsdGeom.Mesh):
            continue
        mesh = UsdGeom.Mesh(prim)
        points = mesh.GetPointsAttr().Get()
        counts = mesh.GetFaceVertexCountsAttr().Get()
        indices = mesh.GetFaceVertexIndicesAttr().Get()
        if points is None or not len(points) or counts is None or indices is None:
            raise ValueError("Empty mesh: " + str(prim.GetPath()))
        if sum(counts) != len(indices) or any(
            index < 0 or index >= len(points) for index in indices
        ):
            raise ValueError("Invalid mesh topology: " + str(prim.GetPath()))
        matrix = cache.GetLocalToWorldTransform(prim)
        bounds = [float("inf")] * 3 + [float("-inf")] * 3
        for point in points:
            world = matrix.Transform(Gf.Vec3d(*point))
            for axis in range(3):
                bounds[axis] = min(bounds[axis], world[axis])
                bounds[axis + 3] = max(bounds[axis + 3], world[axis])
        normals = mesh.GetNormalsAttr().Get()
        normal_values = (
            [[float(v) for v in normal] for normal in normals] if normals is not None else []
        )
        uvs = {}
        for pv in UsdGeom.PrimvarsAPI(prim).GetPrimvars():
            # UE uses st, st1, ... for its mesh UV sets.
            name = str(pv.GetPrimvarName())
            if name == "st" or (name.startswith("st") and name[2:].isdigit()):
                values = pv.ComputeFlattened()
                uvs[name] = {
                    "interpolation": str(pv.GetInterpolation()),
                    "values": (
                        [[float(v) for v in value] for value in values]
                        if values is not None
                        else []
                    ),
                }
        geometry = {
            "points": [[float(v) for v in point] for point in points],
            "counts": list(counts),
            "indices": list(indices),
            "normals": normal_values,
            "normal_interpolation": str(mesh.GetNormalsInterpolation()),
            "uvs": uvs,
            "orientation": str(mesh.GetOrientationAttr().Get()),
            "subdivision": str(mesh.GetSubdivisionSchemeAttr().Get()),
        }
        fingerprint = hashlib.sha256(
            json.dumps(geometry, sort_keys=True, allow_nan=False).encode("utf-8")
        ).hexdigest()
        result["meshes"].append(
            {
                "prim": str(prim.GetPath()),
                "points": len(points),
                "faces": len(counts),
                "triangles": sum(max(0, int(count) - 2) for count in counts),
                "normals": len(normal_values),
                "uv_sets": sorted(uvs),
                "geometry_sha256": fingerprint,
                "world_bounds": bounds,
                "subdivision": geometry["subdivision"],
                "mirrored": matrix.GetDeterminant() < 0,
            }
        )
    if not result["meshes"]:
        raise ValueError("USD stage has no composed meshes.")
    return result
