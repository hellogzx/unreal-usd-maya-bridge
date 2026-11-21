"""Version checks for acceptance runs, independent of either application's API."""

import re

TARGET_UNREAL = "5.8.4"
TARGET_MAYA = "2023"


def require_unreal_version(actual, expected=TARGET_UNREAL):
    """Compare the complete patch release, ignoring Epic's build suffix."""
    match = re.match(r"^(\d+\.\d+\.\d+)(?=$|[-+\s])", str(actual))
    if match is None or match.group(1) != expected or "preview" in str(actual).lower():
        raise ValueError("Acceptance requires Unreal {}, found {}.".format(expected, actual))
    return match.group(1)


def require_maya_version(actual, expected=TARGET_MAYA):
    """Allow updates of the requested Maya year, e.g. 2023.3."""
    match = re.match(r"^(\d{4})(?=$|[.\s])", str(actual))
    if match is None or match.group(1) != expected:
        raise ValueError("Acceptance requires Maya {}, found {}.".format(expected, actual))
    return match.group(1)
