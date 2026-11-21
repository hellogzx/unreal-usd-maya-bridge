"""Deterministic calibration images and a portable USD material fixture."""

import math
import struct
import zlib
from pathlib import Path


def png(path, width, height, pixel):
    def chunk(kind, data):
        return (
            struct.pack("!I", len(data))
            + kind
            + data
            + struct.pack("!I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    raw = b"".join(
        b"\0" + bytes(c for x in range(width) for c in pixel(x, y)) for y in range(height)
    )
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!2I5B", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def build(folder, packed=True):
    folder = Path(folder)
    textures = folder / "textures"
    textures.mkdir(parents=True, exist_ok=True)
    png(
        textures / "pbr_basecolor.png",
        128,
        128,
        lambda x, y: (190, 90, 35) if (x // 16 + y // 16) % 2 else (45, 120, 190),
    )

    def rough(x, y):
        v = round(25 + 205 * x / 127)
        return (v, v, v)

    png(textures / "pbr_roughness.png", 128, 128, rough)
    png(
        textures / "pbr_metallic.png",
        128,
        128,
        lambda x, y: (0, 0, 0) if y < 64 else (255, 255, 255),
    )
    png(
        textures / "pbr_orm.png", 128, 128, lambda x, y: (255, rough(x, y)[0], 0 if y < 64 else 255)
    )

    def normal(x, y):
        nx = 0.45 * math.sin(x * math.pi / 16)
        ny = 0.45 * math.cos(y * math.pi / 16)
        nz = math.sqrt(1 - nx * nx - ny * ny)
        return tuple(round((c + 1) * 127.5) for c in (nx, ny, nz))

    png(textures / "pbr_normal.png", 128, 128, normal)
    from pxr import Usd, UsdGeom, UsdShade, Sdf

    path = folder / ("04_pbr_textures.usda" if packed else "05_pbr_separate_textures.usda")
    stage = Usd.Stage.CreateNew(str(path))
    stage.SetDefaultPrim(UsdGeom.Xform.Define(stage, "/PBR_Demo").GetPrim())
    UsdGeom.SetStageMetersPerUnit(stage, 0.01)
    UsdGeom.SetStageUpAxis(stage, "Y")
    for index, name in enumerate(("SeparateMaps", "PackedORM" if packed else "SeparateMapsB")):
        material = UsdShade.Material.Define(stage, "/PBR_Demo/Looks/" + name)
        surface = UsdShade.Shader.Define(stage, str(material.GetPath()) + "/Surface")
        surface.CreateIdAttr("UsdPreviewSurface")
        surface.CreateInput("useSpecularWorkflow", Sdf.ValueTypeNames.Int).Set(0)
        surface.CreateInput("ior", Sdf.ValueTypeNames.Float).Set(1.5)
        material.CreateSurfaceOutput().ConnectToSource(surface.ConnectableAPI(), "surface")
        reader = UsdShade.Shader.Define(stage, str(material.GetPath()) + "/UV")
        reader.CreateIdAttr("UsdPrimvarReader_float2")
        reader.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("st")

        def texture(label, file, space):
            node = UsdShade.Shader.Define(stage, str(material.GetPath()) + "/" + label)
            node.CreateIdAttr("UsdUVTexture")
            node.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(
                Sdf.AssetPath("textures/" + file)
            )
            node.CreateInput("sourceColorSpace", Sdf.ValueTypeNames.Token).Set(space)
            for key in ("wrapS", "wrapT"):
                node.CreateInput(key, Sdf.ValueTypeNames.Token).Set("repeat")
            node.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(
                reader.ConnectableAPI(), "result"
            )
            return node

        base = texture("BaseColor", "pbr_basecolor.png", "sRGB")
        surface.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(
            base.ConnectableAPI(), "rgb"
        )
        if index == 0 or not packed:
            roughness = texture("Roughness", "pbr_roughness.png", "raw")
            metallic = texture("Metallic", "pbr_metallic.png", "raw")
            rough_output = metal_output = "r"
        else:
            roughness = metallic = texture("ORM", "pbr_orm.png", "raw")
            rough_output, metal_output = "g", "b"
        surface.CreateInput("roughness", Sdf.ValueTypeNames.Float).ConnectToSource(
            roughness.ConnectableAPI(), rough_output
        )
        surface.CreateInput("metallic", Sdf.ValueTypeNames.Float).ConnectToSource(
            metallic.ConnectableAPI(), metal_output
        )
        normal = texture("Normal", "pbr_normal.png", "raw")
        normal.CreateInput("scale", Sdf.ValueTypeNames.Float4).Set((2, 2, 2, 1))
        normal.CreateInput("bias", Sdf.ValueTypeNames.Float4).Set((-1, -1, -1, 0))
        surface.CreateInput("normal", Sdf.ValueTypeNames.Normal3f).ConnectToSource(
            normal.ConnectableAPI(), "rgb"
        )
        mesh = UsdGeom.Mesh.Define(stage, "/PBR_Demo/" + name)
        # Six-faced boxes provide surfaces at several angles for normal previews.
        x = index * 260 - 230
        mesh.CreatePointsAttr(
            [
                (x, 0, -50),
                (x + 200, 0, -50),
                (x + 200, 200, -50),
                (x, 200, -50),
                (x, 0, 50),
                (x + 200, 0, 50),
                (x + 200, 200, 50),
                (x, 200, 50),
            ]
        )
        mesh.CreateFaceVertexCountsAttr([4] * 6)
        mesh.CreateFaceVertexIndicesAttr(
            [4, 5, 6, 7, 1, 0, 3, 2, 0, 4, 7, 3, 5, 1, 2, 6, 3, 7, 6, 2, 0, 1, 5, 4]
        )
        mesh.CreateSubdivisionSchemeAttr("none")
        UsdGeom.PrimvarsAPI(mesh).CreatePrimvar(
            "st", Sdf.ValueTypeNames.TexCoord2fArray, "faceVarying"
        ).Set([(0, 0), (1, 0), (1, 1), (0, 1)] * 6)
        UsdShade.MaterialBindingAPI(mesh).Bind(material)
    stage.GetRootLayer().Save()
    return path
