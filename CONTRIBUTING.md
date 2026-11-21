# Contributing

Read [the development guide](docs/DEVELOPMENT.md) and the current support boundaries
before changing conversion behavior. The repository currently retains copyright;
submitting or accepting a contribution does not create an open-source license.

## Development checks

```bash
python -m pip install -r requirements-dev.txt
python -m black --check .
python -m unittest discover -s tests/unit -p "test_*.py"
python scripts/check_repository.py
```

Changes to Maya scene operations, material connections, Undo, rollback, or the
isolated reader also require the dedicated Maya integration tests. Never run
destructive integration fixtures in an artist's working Maya session.

Use a feature branch and a pull request. Describe the user-visible problem,
resulting behavior, tests actually run, and remaining limitations. Do not claim
support for a host version that has not been exercised.

Keep source USD and textures unchanged, preserve existing scene nodes and global
settings, and retain explicit failure handling for unsupported data.
Do not add private production assets, credentials, machine-specific reports,
generated texture caches, or Maya scene dumps to commits.
