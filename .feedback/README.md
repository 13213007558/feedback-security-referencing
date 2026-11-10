# Feedback task starting environment

Upstream: https://github.com/python-jsonschema/referencing
Upstream commit: `9a82e6c7e5e2e395b61bb4017dc6adc52ac52e7c`
Prepared on macOS with CPython 3.12.11. No external database, queue, or cloud account is required.
The dependency file pins the installed runtime and test packages for the selected baseline. It is not a claim that all optional upstream test suites are installed.

From the repository root:

```sh
export NO_INTERNET=1 TZ=UTC
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r .feedback/requirements.txt -e .
.venv/bin/python -m pytest -q -o addopts= referencing/tests/test_core.py referencing/tests/test_jsonschema.py referencing/tests/test_retrieval.py
```

Scope note: The scope is the command below, not all optional upstream integrations.

Observed baseline (2026-11-10): `171 passed in 0.38s`
Whole-command wall time: 0.734 seconds, exit code 0. This is one local measurement, not a runtime guarantee. The first install is excluded.

This seed adds preparation metadata only. Application sources and upstream tests are unchanged; there is no task solution in this commit.
