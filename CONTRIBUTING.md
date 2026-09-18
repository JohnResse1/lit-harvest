# Contributing

## Development setup

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
cp config.example.yaml config.yaml
.venv/bin/lit-harvest auth set elsevier university_primary
```

## Checks

```bash
.venv/bin/pytest
.venv/bin/ruff check src/lit_harvest tests
.venv/bin/mypy src/lit_harvest
.venv/bin/lit-harvest security scan
```

## Frontend

```bash
./scripts/build_frontend.sh
```

The build output is committed under `src/lit_harvest/api/static/` so users do not need Node.js.

## Pull requests

- Keep acquisition, normalization, scheduling, and API logic in the service layer.
- Do not put provider-specific logic outside `providers/`.
- Never commit `.lit-harvest/`, `config.yaml`, `data/`, or environment files.
- Add tests for new behavior.
