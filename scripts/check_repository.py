"""Check the shareable source tree without requiring Maya or Unreal."""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {".git", ".test-results", "dist", "build", "__pycache__", ".venv"}


def files():
    for path in ROOT.rglob("*"):
        if path.is_file() and not IGNORED.intersection(path.relative_to(ROOT).parts):
            yield path


def check():
    required = (
        "README.md",
        "README_EN.md",
        "LICENSE",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "THIRD_PARTY_NOTICES.md",
        ".gitignore",
        ".gitattributes",
        ".github/workflows/ci.yml",
        "docs/INSTALLATION.md",
        "docs/USER_GUIDE.md",
        "docs/MATERIAL_MAPPING.md",
        "docs/TROUBLESHOOTING.md",
        "docs/UNREAL_EXPORT.md",
        "docs/DEVELOPMENT.md",
        "docs/VALIDATION.md",
        "docs/images/simple-pbr.png",
    )
    errors = ["Missing required file: " + name for name in required if not (ROOT / name).is_file()]
    private_path = re.compile(r"(?i)[a-z]:[/\\]users[/\\]|/(?:Users|home)/[^/\s\"']+/")
    token = re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}\b")
    for path in files():
        relative = path.relative_to(ROOT).as_posix()
        if path.stat().st_size > 10 * 1024 * 1024:
            errors.append("Unexpected large source-tree file: " + relative)
        if path.suffix not in (".py", ".md", ".yml", ".yaml", ".toml", ".txt", ".usda"):
            continue
        text = path.read_text(encoding="utf-8")
        if private_path.search(text):
            errors.append("Machine-specific home path: " + relative)
        if token.search(text):
            errors.append("Possible credential in file: " + relative)
        if path.suffix == ".py":
            try:
                ast.parse(text, filename=relative, feature_version=(3, 9))
            except SyntaxError as error:
                errors.append("Python 3.9 syntax error in {}: {}".format(relative, error))
        if path.suffix == ".md":
            for link in re.findall(r"\]\(([^)]+)\)", text):
                target = link.strip("<>").split("#", 1)[0]
                if not target or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
                    continue
                if not (path.parent / target).exists():
                    errors.append("Broken relative link in {}: {}".format(relative, target))
        if path.suffix == ".usda":
            for asset in re.findall(r"@([^@\r\n]+)@", text):
                if Path(asset).is_absolute() or not (path.parent / asset).is_file():
                    errors.append(
                        "Non-portable/missing sample asset in {}: {}".format(relative, asset)
                    )
    if errors:
        raise RuntimeError("\n".join(errors))
    print("Repository checks passed.")


if __name__ == "__main__":
    check()
