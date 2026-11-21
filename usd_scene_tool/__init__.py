"""USD scene and material tool for Maya 2023."""

__version__ = "0.9.2"


def show():
    from .simple_pbr import show as show_window

    return show_window()


def show_advanced():
    from .ui import show as show_window

    return show_window()
