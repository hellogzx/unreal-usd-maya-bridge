# Changelog

## [0.9.2] - 2026-11-21

### Changed

- Organized the working tool as a standalone GitHub repository.
- Formatted Python source consistently and added portable tests and release tooling.
- Added Chinese/English documentation, CI, issue/PR templates, and explicit scope notes.
- Changed the simple sample button to use bundled original synthetic PBR geometry.
- Kept external models, machine logs, credentials, and unrelated prototypes outside the repository.

## [0.9.1] - 2026-11-21

### Fixed

- Recover zero-mesh native USD imports through an isolated local Maya reader.
- Preserve the working scene, Undo, and material reconstruction during recovery.
- Add timeout/failure handling and disclose possible instance expansion in the fallback.

## [0.9.0] - 2026-11-21

### Added

- Simple-window target selection for editable preview Phong material reconstruction.
- Roughness-to-highlight conversion and approximate metallic diffuse/specular mixing.

## [0.8.0] - 2026-11-20

### Added

- Minimal standalone Maya UI with one-click USD import and four optional map fields.
- Per-material replacements, missing-image repair, and unbound-mesh assignment with st UV.

## [0.7.0] - 2026-11-20

### Added

- Physical extraction of scalar channels into independent grayscale PNGs.
- Content-addressed cache verification, repair, and 8/16-bit integer preservation.

## [0.6.0]

### Added

- Standard Surface PBR reconstruction, ORM swizzles, and tangent normals.

## [0.5.0]

### Added

- Static perspective camera transfer and explicit, undoable frame matching.
- Existing Unreal exporter baseline retained by later Maya receiver releases.
