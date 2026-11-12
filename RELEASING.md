# Releasing to PyPI

These steps are for maintainers publishing a new version of `simple-serialize`.
The package uses setuptools with its metadata and package configuration in
`pyproject.toml`.

## Prepare a release

1. Make sure the changes intended for release are complete and the working tree
   is in the expected state.
2. Update the `version` field in `pyproject.toml`. PyPI does not allow an
   already-published version to be uploaded again.
3. Run the tests and build-tool checks from the repository root:

   ```shell
   python -m pip install --upgrade build twine
   python -m pip install -e '.[test]'
   python -m pytest
   python -m build
   python -m twine check dist/*
   ```

   The build creates a source distribution and a wheel in `dist/`. Check that
   the directory contains only the artifacts for the version being released.

## Test the upload (optional)

Upload the artifacts to TestPyPI:

```shell
python -m twine upload --repository testpypi dist/*
```

Use `__token__` as the username and a TestPyPI API token as the password when
prompted. Then verify that the package can be installed:

```shell
python -m pip install --index-url https://test.pypi.org/simple/ simple-serialize
```

## Publish to PyPI

Create a PyPI account and API token if needed, then upload the checked
artifacts:

```shell
python -m twine upload dist/*
```

When prompted, use `__token__` as the username and the PyPI API token as the
password. Keep the token secret; do not commit it or put it in shell commands
that may be saved in history. For automated releases, prefer configuring
PyPI Trusted Publishing with GitHub Actions instead of storing a long-lived
token.

After publishing, verify the release page and install the package from PyPI:

```shell
python -m pip install simple-serialize
```
