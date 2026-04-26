---
name: rcli
description: Use when uploading, syncing, listing, or deleting files in FollowHub's Cloudflare R2 bucket, especially when credentials live in ~/.followhub/config.yaml or FOLLOWHUB_CONFIG and the agent should use the bundled R2 rclone helper.
---

# Rcli

Use this skill when an agent needs direct file operations against FollowHub's Cloudflare R2 bucket.

## Preferred Entry Point

Prefer the bundled helper script over handwritten shell snippets:

```bash
python3 "$SKILL_DIR/scripts/rcli.py" --help
```

Use raw `rclone` directly only when the helper script does not cover the operation.

## Scope

- Use the bundled helper script first.
- Do not build another uploader first.
- Prefer `copyto`, `copy`, `sync`, `lsjson`, `deletefile`, `delete`.
- Treat `purge` as destructive and require explicit user approval before running it.

## Config Source

Resolve the config file in this order:

1. `FOLLOWHUB_CONFIG`
2. `Followhub_Config`
3. `~/.followhub/config.yaml`

For repo-local development, prefer either of these:

```bash
export FOLLOWHUB_CONFIG="$PWD/config.yaml"
```

or:

```bash
python3 "$SKILL_DIR/scripts/rcli.py" --config-file ./config.yaml ...
```

Read the `rclone` section. Expected shape:

```yaml
rclone:
  account_id: your-cloudflare-account-id
  access_key_id: your-r2-access-key-id
  secret_access_key: your-r2-secret-access-key
  bucket: followhub
  public_base_url: https://pub-xxxx.r2.dev
```

Required keys:

- `account_id`
- `access_key_id`
- `secret_access_key`
- `bucket`

Optional keys:

- `public_base_url`

Never print secrets back to the user.

## Rclone Check

Before any operation, check whether `rclone` exists:

```bash
python3 "$SKILL_DIR/scripts/rcli.py" check
```

If `rclone` is missing, install it first.

## Install Tutorial

The helper can print the tutorial directly:

```bash
python3 "$SKILL_DIR/scripts/rcli.py" install-help
```

Prefer the platform package manager when available.

macOS:

```bash
brew install rclone
```

Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install -y rclone
```

Universal Linux/macOS install from the official project:

```bash
sudo -v
curl https://rclone.org/install.sh | sudo bash
```

Windows:

```powershell
winget install Rclone.Rclone
```

After install, verify again:

```bash
rclone version
```

If installation needs network or elevated permissions, ask the user before running it.

## Temporary R2 Remote

Do not rely on a preconfigured global `rclone` remote. The helper script creates a temporary config file from the FollowHub YAML values, then runs `rclone` with `--config`.

Template:

```ini
[followhub-r2]
type = s3
provider = Cloudflare
access_key_id = <access_key_id>
secret_access_key = <secret_access_key>
endpoint = https://<account_id>.r2.cloudflarestorage.com
acl = private
no_check_bucket = true
```

If you must run raw `rclone`, use this shell pattern:

```bash
TMP_RCLONE_CONFIG="$(mktemp)"
trap 'rm -f "$TMP_RCLONE_CONFIG"' EXIT
```

Then write the temporary config and use `--config "$TMP_RCLONE_CONFIG"` on every `rclone` command.

Remote object paths should use this form:

```text
followhub-r2:<bucket>/<key>
```

Example:

```text
followhub-r2:followhub/images/2026/04/example.png
```

## Common Operations

### Upload one file

Preferred helper command:

```bash
python3 "$SKILL_DIR/scripts/rcli.py" copyto ./xx.png xxpng
```

After success:

- If `public_base_url` exists, return `public_base_url + "/" + key`
- Otherwise return `r2://<bucket>/<key>`

Example returned URL:

```text
https://pub-xxxx.r2.dev/xxpng
```

### Upload a directory without deleting remote extras

```bash
python3 "$SKILL_DIR/scripts/rcli.py" copy ./local-dir some/prefix/
```

### Mirror a directory exactly

Use `sync` only when the user wants remote extras removed:

```bash
python3 "$SKILL_DIR/scripts/rcli.py" sync ./local-dir some/prefix/
```

Warning: `sync` deletes remote files that are not present locally.

### List objects

Prefer JSON output for agent-readable results:

```bash
python3 "$SKILL_DIR/scripts/rcli.py" --json lsjson some/prefix/
```

### Delete one file

```bash
python3 "$SKILL_DIR/scripts/rcli.py" deletefile some/prefix/file.png
```

### Delete objects under a prefix

```bash
python3 "$SKILL_DIR/scripts/rcli.py" delete some/prefix/
```

### Purge a prefix completely

Only do this after the user explicitly asks for a destructive delete:

```bash
python3 "$SKILL_DIR/scripts/rcli.py" purge some/prefix/ --force
```

### Resolve a public URL without uploading

```bash
python3 "$SKILL_DIR/scripts/rcli.py" url some/prefix/file.png
```

## Usage Rules

- For a single file upload, use `copyto`, not `copy`.
- For directory uploads that should not delete remote files, use `copy`.
- For exact mirroring, use `sync`.
- For a single file removal, use `deletefile`.
- For bulk deletion under a prefix, use `delete`.
- For full prefix removal including the directory marker, use `purge` only with explicit approval.
- Prefer `--json` for list operations when another agent or script will consume the output.

## User-Facing Response Format

Keep responses short and outcome-focused.

Upload example:

```text
Uploaded to https://pub-xxxx.r2.dev/xxpng
```

Delete example:

```text
Deleted followhub/xxpng
```

List example:

```text
Listed 14 objects under followhub/some/prefix/
```

If an operation fails, include:

- the `rclone` subcommand used
- the target path
- the main stderr reason

Do not dump secrets or full temporary config contents.
