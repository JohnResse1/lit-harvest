# Operations

## First run

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
cp config.example.yaml config.yaml
.venv/bin/lit-harvest auth set elsevier university_primary
.venv/bin/lit-harvest doctor --network
```

The UI binds only to `127.0.0.1` by default. Do not bind publicly: v0.1 has no authentication.

## Local instance isolation

The repository ships code only. Each user who clones it gets an independent local instance:

```text
./data/lit_harvest.db      one SQLite file per user
./data/papers/             one raw/normalized tree per user
./.lit-harvest/            one secret + instance ID per user
```

`lit-harvest ui` binds `127.0.0.1` and refuses non-loopback hosts unless
`server.allow_non_loopback: true` is set. Verify which instance you are looking at:

```bash
lit-harvest ui          # prints user, hostname, instance ID
curl -sS http://127.0.0.1:8765/api/instance
```

## Credential storage

The recommended local setup stores secrets outside the repository:

```bash
lit-harvest auth set elsevier university_primary
lit-harvest auth list
lit-harvest auth test elsevier university_primary
lit-harvest auth remove elsevier university_primary
```

The command writes to `<project>/.lit-harvest/secrets.json` with permission `0600`, and the
directory is ignored by Git. `config.yaml` stores only a reference such as
`file:elsevier:university_primary`. The file is outside SQLite, logs, API responses, and browser
state. Set `LIT_HARVEST_SECRET_BACKEND=keychain` or pass an explicit `keychain:` reference only if
you prefer the operating-system keyring.

## Quota and credential policy

Credential failover is allowed only across independently authorized credentials. A cooldown or
exhaustion for an institution-scoped quota blocks credentials in that institution. Unknown scope is
treated conservatively and also blocks failover. HTTP 429, timeouts, and 5xx responses are retried
with bounded backoff; 400/401/403/404 are not repeatedly retried.

## Resume behavior

- Existing successful raw XML is reused instead of downloaded again.
- Pending/retry/waiting jobs remain in SQLite across process restarts.
- `lit-harvest parse` reprocesses downloaded raw files that lack normalized output.
- Writes to raw/normalized/state files are atomic.
- Permanent failures remain visible and are not silently retried.

## Storage layout

```text
data/
├── lit_harvest.db
├── exports/
└── papers/
    └── 10.1016_j.example/
        ├── raw/
        │   └── elsevier_xml.xml
        ├── normalized/
        │   └── paper.json
        └── state.json
```
