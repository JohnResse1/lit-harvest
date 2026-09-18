# Security Policy

## Credential handling

Literature Harvester never stores plaintext API keys in SQLite or committed configuration.

Recommended local setup:

```bash
lit-harvest auth set elsevier university_primary
```

This stores the secret in the project-local file `.lit-harvest/secrets.json` with permission `0600`.
The directory is excluded by `.gitignore`. The project-local backend is the default because it keeps
the credential together with the project without requiring shell environment variables.

Optional backends:

```text
file:provider:name         project-local 0600 secrets file
keychain:service:account   operating-system keyring
env:NAME                   CI/container compatibility only
```

`config.yaml` stores only a secret reference, never the secret value.

## What is never logged

- API keys
- authorization headers
- secret file contents
- request bodies containing credentials

## Before publishing a repository

Run:

```bash
lit-harvest security scan
git status --short
git diff --cached
```

The scan looks for common key formats and accidental secret files outside ignored paths. It is a
safety net, not a replacement for reviewing the staged diff.

## Reporting a vulnerability

Do not open a public issue for an active credential leak. Revoke the credential first, then contact
the maintainers privately with the repository URL and the affected commit or file.
