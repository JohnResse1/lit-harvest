# Publishing to GitHub

## 1. Verify the repository is clean

```bash
git status --short
lit-harvest security scan
```

The scan fails if it finds likely credentials or a protected secret file tracked by Git.

## 2. Confirm local state is ignored

```bash
git check-ignore -v .lit-harvest/secrets.json config.yaml data/lit_harvest.db .env
```

All four paths must be reported as ignored.

## 3. Create the first commit

```bash
git add .
git status --short
git diff --cached --stat
git commit -m "Initial open-source release of Literature Harvester"
```

Review `git status --short` before committing. Do not use `git add -f` on ignored secret paths.

## 4. Create a private GitHub repository

With GitHub CLI:

```bash
gh auth login
gh repo create lit-harvest --private --source=. --remote=origin --push
```

Or create the repository in the GitHub web UI and then run:

```bash
git remote add origin git@github.com:YOUR_ACCOUNT/lit-harvest.git
git push -u origin main
```

## 5. Before making it public

- Confirm `.lit-harvest/` was never committed.
- Confirm `config.yaml` and `data/` were never committed.
- Run `lit-harvest security scan`.
- Revoke any key that may ever have been pushed.
- Review the GitHub secret-scanning and push-protection settings.
