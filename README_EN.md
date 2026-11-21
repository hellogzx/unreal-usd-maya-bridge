# Unreal USD Maya Bridge

[中文](README.md) · Maya receiver **v0.9.2** · Unreal exporter **v0.5.0**

A file-based static-scene previs workflow from Unreal through USD to Maya.
The Maya tool also works independently: import a supported USD and reconstruct
Standard Surface or editable preview Phong materials with four separate maps.

## Quick start

1. Download a Maya release ZIP or the repository and keep the complete folder.
2. In Maya 2023, drag `launch_usd_pbr_simple.py` into a viewport.
3. Select a USD, choose Standard Surface or Phong, and click Import.
4. Leave the four map fields empty to use the USD's authored material.
5. Select the result, press **F** in the viewport to frame it, and **6** to show textures.

`PBR 示例` selects a bundled synthetic test scene without importing it.
The optional `install_usd_tool.py` creates a dedicated shelf button.
No MCP server, AI service, API key, or pip installation is needed at runtime.

## Material channels

| Map | Standard Surface | Preview Phong |
| --- | --- | --- |
| Base Color | `baseColor`, sRGB | `color` and approximate metal specular tint |
| Metallic | `metalness`, Raw | Approximate diffuse/specular/reflection mixing |
| Roughness | `specularRoughness`, Raw | Bounded conversion to `cosinePower` |
| Normal | Raw tangent RGB through `bump2d` | Same |

Authored ORM swizzles are extracted into independent grayscale PNGs. Normal
remains a separate RGB map. Phong conversion is a preview approximation,
not a physically equivalent PBR shader.

## Supported scope

- Tested Maya runtime: Windows, Maya 2023, Maya USD 0.16.0, USD SDK 0.21.11.
- Static geometry, placement, supported perspective cameras and material bindings.
- Centimeters, Y-up, static UsdPreviewSurface metal/rough materials, st UV, repeat wrap.
- The Unreal exporter has prior local UE 5.8.4 acceptance; it exports static gray
  geometry/cameras, not arbitrary UE shaders or baked materials.
- No animation, skeletons, UDIM, MaterialX, Gazebo, opacity, displacement, AO
  composition, emission, UV transforms, or full Nanite source reconstruction.

An empty native mesh import can recover through the installed local `mayapy`
without unloading the working session's plugins or clearing Undo. This path has
startup overhead and may expand shared instances. Source files remain unchanged.

## Development

```bash
python -m unittest discover -s tests/unit -p "test_*.py"
python scripts/check_repository.py
python scripts/build_release.py
```

See [development](docs/DEVELOPMENT.md), [validation](docs/VALIDATION.md),
[installation](docs/INSTALLATION.md), and [changelog](CHANGELOG.md).
CI runs Python checks; DCC integration requires a separate licensed Maya process.

Original code currently retains all rights; no open-source redistribution
license has been granted. See [LICENSE](LICENSE) and
[third-party notices](THIRD_PARTY_NOTICES.md). External photographic models and
their archives are intentionally distributed separately from this repository.
