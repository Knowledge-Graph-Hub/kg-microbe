# Tox Testing Guide

This guide explains how to run the project's quality checks and tests using [tox](https://tox.wiki/), and documents common errors and solutions.

## Prerequisites

1. **Install dependencies** (including tox and kgx):

   ```bash
   poetry install
   ```

   Or, if using the project venv directly:

   ```bash
   pip install tox kgx
   ```

2. **Python version**: The project supports Python 3.10–3.13. **Python 3.14 is not fully supported** due to a dependency (`requests_ftp`) that relies on the removed `cgi` module. For full test coverage, use Python 3.11 or 3.12:

   ```bash
   poetry env use python3.12
   poetry install
   ```

## Running Tox

From the project root:

```bash
poetry run tox
```

Or, if the venv is activated:

```bash
.venv/bin/tox
```

## Tox Environments

| Environment         | Purpose                                      |
|---------------------|----------------------------------------------|
| `coverage-clean`    | Erases coverage data                         |
| `format`            | Runs Black and Ruff (format + fix)           |
| `lint`              | Runs Ruff (style/lint checks)                 |
| `codespell-write`   | Spell-check and auto-correct                 |
| `docstr-coverage`   | Checks docstring coverage                    |
| `py`                | Runs pytest (unit tests)                     |

### Run specific environments

```bash
poetry run tox -e format      # Format and lint only
poetry run tox -e lint        # Lint only
poetry run tox -e py          # Tests only
poetry run tox -e format,lint,py  # Multiple envs
```

## How the `py` Environment Works

The `py` environment is configured to use the project's `.venv` directly (rather than creating an isolated tox env). This ensures all project dependencies (kghub_downloader, kgx, oaklib, etc.) are available.

**Command used**: `{toxinidir}/.venv/bin/python -m pytest`

This requires that:

1. The project has a `.venv` directory (created by `poetry install`)
2. All dependencies are installed in that venv

## Common Errors and Solutions

### 1. `ModuleNotFoundError: No module named 'kghub_downloader'`

**Cause**: The test runner is using a Python environment that doesn't have the project's dependencies installed. This often happens when `poetry run pytest` uses a different Poetry-managed env (e.g., Python 3.11) than the one where you installed packages.

**Solution**:

- Run tox from the project venv: `.venv/bin/tox`
- Or ensure Poetry uses the correct env: `poetry env use .venv/bin/python`
- The tox `py` env is configured to call `.venv/bin/python -m pytest` directly to avoid this.

---

### 2. `ModuleNotFoundError: No module named 'kgx'`

**Cause**: The `kgx` package is not installed. It is a project dependency but may be missing if `poetry install` failed or was never run.

**Solution**:

```bash
poetry run pip install kgx
# or
poetry install
```

---

### 3. `ModuleNotFoundError: No module named 'pytest'`

**Cause**: tox created an isolated env (e.g., `.tox/py/`) with only `pip` installed. This occurs when tox does not use the project venv.

**Solution**: The tox config uses `.venv/bin/python -m pytest` so the project venv (with pytest) is used. Ensure `.venv` exists and has pytest installed: `poetry install` or `pip install pytest` in the venv.

---

### 4. `gzip.BadGzipFile: Not a gzipped file`

**Cause**: The metatraits transform tried to open a plain `.jsonl` file with `gzip.open()`. The `_open_jsonl` helper was updated to check the file extension: use gzip only for `.gz` files, plain `open()` otherwise.

**Solution**: This is fixed in the codebase. If you see it, ensure you have the latest `metatraits.py` with the extension-based logic in `_open_jsonl`.

---

### 5. `TypeError: 'DummyTqdm' object is not iterable`

**Cause**: Code used `for x in DummyTqdm(iterable)` but `DummyTqdm` is not iterable. It was designed as a context manager, not an iterable wrapper.

**Solution**: Use conditional iteration instead:

```python
iterable = tqdm(files, desc="...") if show_status else files
for item in iterable:
    ...
```

---

### 6. `AttributeError: 'str' object has no attribute 'get'`

**Cause**: When loading `custom_curies.yaml`, some values (e.g., `category`, `predicate`) are strings, not dicts. Code assumed all values were dicts and called `.get()` on them.

**Solution**: Add a type check before accessing dict methods:

```python
for key, value in custom_map.items():
    if not isinstance(value, dict):
        continue
    # ... use value.get(...)
```

---

### 7. `ModuleNotFoundError: No module named 'cgi'` (Python 3.14)

**Cause**: The `requests_ftp` package imports the `cgi` module, which was removed in Python 3.13. On Python 3.14, this breaks imports for any module that depends on `requests_ftp` (e.g., `rhea_mappings`).

**Solution**:

- Use Python 3.11 or 3.12 for the project:
  ```bash
  poetry env use python3.12
  poetry install
  poetry run tox
  ```
- Or run only tests that don't trigger this import:
  ```bash
  poetry run pytest tests/test_metatraits.py -v
  ```

---

### 8. `poetry install` fails (pydantic-core / PyO3 / Python 3.14)

**Error**: `error: the configured Python interpreter version (3.14) is newer than PyO3's maximum supported version (3.13)`

**Cause**: Some dependencies (e.g., `pydantic-core`) use Rust/PyO3 and do not yet support Python 3.14.

**Solution**: Use Python 3.11 or 3.12:

```bash
poetry env use python3.12
poetry install
```

---

### 9. `py: failed with pytest is not allowed, use allowlist_externals to allow it`

**Cause**: tox blocks external commands by default. Running `pytest` directly was treated as an external command.

**Solution**: The tox config uses `{toxinidir}/.venv/bin/python -m pytest`, which runs Python from the project venv. No `allowlist_externals` for `pytest` is needed when using `python -m pytest`.

---

### 10. `ERROR collecting test_dedup.py`

**Cause**: A `test_dedup.py` file in the project root was being collected by pytest. It may import project code that triggers dependency issues.

**Solution**: Pytest is configured with `testpaths = ["tests"]` in `pyproject.toml`, so only the `tests/` directory is collected. Root-level test files are ignored.

---

## Running Tests Without Tox

To run tests directly:

```bash
poetry run pytest
poetry run pytest tests/test_metatraits.py -v
poetry run pytest tests/ -k "metatraits" -v
```

To run individual quality checks:

```bash
poetry run black kg_microbe/ tests/
poetry run ruff check kg_microbe/ tests/
poetry run codespell kg_microbe/ tests/ --write-changes -S 'kg_microbe/transform_utils/*/tmp/*' -S kg_microbe/transform_utils/bacdive/metabolite_mapping.json -S 'kg_microbe/transform_utils/ontologies/xrefs/*' -S 'tests/resources/traits/*'
poetry run docstr-coverage kg_microbe/ tests/ --skip-private --skip-magic
```

## Recommended Workflow

1. Use Python 3.11 or 3.12 for full compatibility.
2. Run `poetry install` to set up the environment.
3. Run `poetry run tox` before committing to ensure all checks pass.
4. If `poetry install` fails, try `poetry env use python3.12` and retry.
