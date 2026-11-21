# Dependencies and sample provenance

The application source in this repository is the project's original code.
The repository does not bundle Maya, Unreal Engine, OpenUSD, Qt, PySide,
Maya MCP servers, or third-party model libraries.

| Dependency | How it is used |
| --- | --- |
| Autodesk Maya 2023 / Maya USD | User-installed host, native USD importer, bundled Python and USD SDK |
| PySide2 / Qt | Provided by Maya; used for the UI and raw PNG/JPEG channel extraction |
| Unreal Engine Python / USD Importer | User-enabled editor plugins, required only for the optional Unreal exporter |
| Python standard library | Validation, scene package metadata, hashing, subprocess recovery, release packaging |
| Black | Optional development formatter, pinned in `requirements-dev.txt` |
| GitHub Actions | CI references the official checkout and setup-python actions; their source is not bundled |

Use each host and dependency under its own license. This repository's copyright
notice does not grant a Maya or Unreal Engine license.

## Included samples

`usd_learning/` contains original, synthetic USD scenes and calibration PNGs:
simple geometric shapes, a checkerboard, roughness/metallic gradients, a tangent
normal test pattern, and packed versus separate channel comparisons.

The photographic tea bowl, Antique Camera, their source archives, and Unreal
Engine's built-in asset geometry are **not included** in this repository or its
release ZIPs. Tests generate their own disposable geometry and cameras.

## Optional external test assets

- [Antique Camera — Khronos Sample Assets](https://github.com/KhronosGroup/glTF-Sample-Assets/tree/main/Models/AntiqueCamera):
  author Maximillan Kamps / UX3D. The source asset declares CC0; the UX3D
  logo/trademark is excluded from that grant, and upstream metadata has its own
  license. Consult the asset's current `LICENSE.md` before reuse.
- [Needle USD conversion catalog](https://asset-explorer.needle.tools/AntiqueCamera):
  provides USDZ conversions. Unpack and adapt a copy for the supported static
  four-channel workflow; preserve its attribution and source license.

Downloaded external models remain separate from the code repository.
