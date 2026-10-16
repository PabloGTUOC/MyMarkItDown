# MyMarkItDown (mdbridge)

A stateless document-to-Markdown conversion web service powered by Microsoft's [MarkItDown](https://github.com/microsoft/markitdown) Python library.

Designed to run on a home NAS (OpenMediaVault) and be accessed from any browser or CLI script through a Cloudflare Tunnel, turning uploaded documents (PDF, Word, Excel, PowerPoint, CSV, HTML, EPUB, Outlook MSG) into clean Markdown suitable for feeding LLMs.

---

## Features

- **Stateless & Private:** Documents are converted in-memory or via request-scoped temporary files in `/tmp` that are immediately removed upon completion. File contents and Markdown text are never logged.
- **Dual Frontend Modes:**
  - **Folder-to-Folder (Chromium desktop):** Uses the browser **File System Access API** (`showDirectoryPicker`) to read a local input folder and write converted `.md` files directly into a local output folder, mirroring the input directory structure.
  - **ZIP Download Fallback (Safari / Firefox):** Allows folder/file selection via standard inputs or drag-and-drop, converting files and bundling the output tree into a single downloadable `.zip` file.
- **Incremental Conversions:** Automatically skips files when a corresponding `.md` target already exists with a newer or equal modification time (`lastModified >= source.lastModified`).
- **Collision Protection:** When two supported files in the same directory share a stem (e.g. `Report.pdf` and `Report.docx`), both are output as `<name>.<ext>.md` (`Report.pdf.md` and `Report.docx.md`). Non-colliding files output as `<stem>.md`.
- **Strict File Sniffing:** Extension allow-listing paired with magic-byte inspection (`filetype`). Images, audio, and video files are rejected even if renamed.
- **Concurrency & Resource Throttling:** Server-side concurrency control via asyncio semaphores with per-file timeouts.

---

## Supported Formats

| Category | Extensions | Notes |
|---|---|---|
| **PDF** | `.pdf` | Converted via `pdfminer.six` |
| **Word** | `.docx` | Converted via `mammoth` |
| **PowerPoint** | `.pptx` | Converted via `python-pptx` |
| **Excel** | `.xlsx`, `.xls` | Converted via `openpyxl` / `xlrd` |
| **Data & Text** | `.csv`, `.json`, `.xml`, `.txt`, `.md` | Plaintext / structured tables |
| **Web** | `.html`, `.htm` | Clean HTML content extraction |
| **E-books** | `.epub` | Converted via `ebooklib` / zip parsing |
| **Outlook** | `.msg` | Converted via `olefile` |

> **Out of Scope (Rejected):** Images (`.jpg`, `.png`, `.webp`, `.heic`, …), audio/video, remote URL fetching, and plain `.zip` archives.

---

## Local Development Commands

Prerequisites: Python 3.12 and [`uv`](https://docs.astral.sh/uv/).

```bash
# Install dependencies into .venv
uv sync

# Run development server with live reload on :8000
uv run uvicorn app.main:app --reload

# Run tests
uv run pytest -q

# Run frontend unit tests with Node.js
node --test tests/js/plan.test.mjs

# Code linting and formatting check
uv run ruff check . && uv run ruff format --check .

# Run dev container via Docker Compose
docker compose -f docker-compose.dev.yml up --build
```

---

## API Reference

### `GET /healthz`
Service liveness check used by container health checks and Uptime Kuma.
- **Response:** `200 OK` `{"status": "ok"}`

### `GET /api/formats`
Returns the server allow-list of supported file extensions.
- **Response:** `200 OK` `[".pdf", ".docx", ".pptx", ...]`

### `POST /api/convert`
Convert a single uploaded document to Markdown.

- **Content-Type:** `multipart/form-data`
- **Form Fields:** `file` (binary file upload)
- **Query Parameters:**
  - `frontmatter` (`true` | `false`, default: `true`): Prepend YAML metadata header (`source_file`, `source_size_bytes`, `converted_at`, `converter`).
  - `format` (`md` | `json`, default: `md`): Output format.
    - `md`: Returns `text/markdown; charset=utf-8`.
    - `json`: Returns `application/json` (`{"markdown": "...", "warnings": [], "converter_version": "..."}`).

#### `curl` Examples

```bash
# Basic file conversion
curl -sS -F "file=@report.pdf" http://127.0.0.1:8000/api/convert -o report.md

# Convert with JSON output and no frontmatter
curl -sS -F "file=@data.csv" "http://127.0.0.1:8000/api/convert?frontmatter=false&format=json"

# Conversion through Cloudflare Tunnel with Cloudflare Access Service Token
curl -sS \
  -H "CF-Access-Client-Id: $CF_ACCESS_CLIENT_ID" \
  -H "CF-Access-Client-Secret: $CF_ACCESS_CLIENT_SECRET" \
  -F "file=@Q3_risk.xlsx" \
  https://md.opinasdeque.es/api/convert -o Q3_risk.md
```

#### Error Responses

Error responses return JSON with standard error codes:
```json
{
  "error": "unsupported_type",
  "detail": "Extension '.zip' is not supported."
}
```
Available error codes: `unsupported_type`, `image_rejected`, `too_large`, `length_required`, `timeout`, `conversion_failed`.

---

## Configuration

All configuration options are defined in `app/config.py` and can be set via environment variables or a `.env` file:

| Variable | Default | Description |
|---|---|---|
| `MAX_UPLOAD_MB` | `95` (production compose: `1024`) | Maximum upload size per file (Cloudflare Free plan caps bodies at 100 MB). |
| `CONVERT_TIMEOUT_S` | `120` (production compose: `600`) | Maximum conversion time in seconds per file before returning 504. |
| `MAX_CONCURRENCY` | `2` (production compose: `1`) | Max concurrent conversions handled concurrently by the worker threadpool. |
| `ENABLE_FRONTMATTER_DEFAULT` | `true` | Default for whether YAML frontmatter is prepended. |
| `LOG_LEVEL` | `INFO` | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `ROOT_PATH` | `""` | Base path prefix if mounted behind a reverse proxy sub-path. |

### Sizing `/tmp` and Memory

- **`/tmp` tmpfs**: Starlette spools uploaded files larger than 1 MB directly to `/tmp`. Because upload and conversion concurrency is gated by `MAX_CONCURRENCY`, `/tmp` needs about `MAX_CONCURRENCY` × `MAX_UPLOAD_MB` plus ~200 MB headroom (e.g. 1 × 1024 MB + ~200 MB ≈ 1300 MB; the production compose sets `tmpfs: ["/tmp:size=1300m"]` within `mem_limit: 3g`).
- **`mem_limit`**: In Linux Docker, tmpfs memory counts directly against the container's `mem_limit`.
- **Parsing memory**: Conversions of large tabular formats (CSV, XLSX) build the entire parsed table in memory during conversion, so keep sufficient container memory allocated beyond the tmpfs usage.

### Upload Limits and Cloudflare

Via the Cloudflare Free plan, request bodies larger than 100 MB are rejected by Cloudflare edge servers, and responses taking longer than ~100 s receive an HTTP 524 timeout. Therefore, the production container's 1 GB upload limit and 600 s conversion timeout will only take full effect for direct LAN access added later (or on a paid Cloudflare tier). For all traffic routed through Cloudflare Tunnel, keep uploads within the 100 MB / ~100 s boundary.

---

## Batch Script Usage

`scripts/mdbridge-batch.sh` provides folder-to-folder mirroring via the API with the same naming and collision rules as the web UI.

```bash
# Basic usage (defaults to https://md.opinasdeque.es)
./scripts/mdbridge-batch.sh /path/to/input /path/to/output

# Production via Cloudflare Access service token (disabling incremental skip with -f)
export CF_ACCESS_CLIENT_ID="<service-token-client-id>"
export CF_ACCESS_CLIENT_SECRET="<service-token-client-secret>"
./scripts/mdbridge-batch.sh -u https://md.opinasdeque.es -f /path/to/input /path/to/output

# Local dev compose (published on port 8000)
./scripts/mdbridge-batch.sh -u http://localhost:8000 /path/to/input /path/to/output

# Non-recursive (top-level files only) without frontmatter
./scripts/mdbridge-batch.sh -r -n /path/to/input /path/to/output
```

If `CF_ACCESS_CLIENT_ID` and `CF_ACCESS_CLIENT_SECRET` environment variables are set, the script automatically attaches them as request headers.

---

## NAS Production Deployment Runbook

Deploying to an x86 OpenMediaVault NAS behind Cloudflare Tunnel and Nginx Proxy Manager (NPM):

### Prerequisites

- **SSH Key Authentication:** Passwordless SSH key login to the NAS (`ssh-copy-id user@192.168.50.174`).
- **Directory Permissions:** `NAS_DIR` (default: `/srv/docker/mdbridge`) must be writable by the SSH user.
- **Docker Access:** Recommend adding the SSH user to the `docker` group on the NAS (`sudo usermod -aG docker $USER`). If using `NAS_DOCKER="sudo docker"`, the SSH user must have passwordless `sudo` configured for Docker in `/etc/sudoers` because SSH executes commands non-interactively without a TTY.
- **Network:** The external Docker network `proxy-network` must exist on the NAS (`docker network create proxy-network`).

### 1. Deploy via `scripts/deploy-nas.sh`

The automated deployment script handles test verification, fail-fast network checks, `linux/amd64` building, SSH transfer, remote directory/compose setup, forced container recreation, and health check polling:

```bash
# Basic deployment (runs pytest and ruff first)
NAS_HOST=user@192.168.50.174 ./scripts/deploy-nas.sh

# Fast deployment skipping tests (e.g. during testing or when verified in CI)
NAS_HOST=user@192.168.50.174 ./scripts/deploy-nas.sh --skip-tests

# Preview the exact deployment plan without executing commands
NAS_HOST=user@192.168.50.174 ./scripts/deploy-nas.sh --dry-run
```

**Environment Variables & Options:**
- `NAS_HOST`: (Required) Target SSH host, e.g. `user@192.168.50.174`.
- `NAS_DIR`: Remote target directory (default: `/srv/docker/mdbridge`).
- `NAS_DOCKER`: Remote docker command (default: `docker`, or `sudo docker`).
- `--skip-tests`: Skip local `pytest` and `ruff` checks before deployment.
- `--dry-run`: Print every planned command instead of executing.

**First-Run `.env` Behavior:**
On initial deployment, the script copies `.env.example` to `$NAS_DIR/.env` only if `$NAS_DIR/.env` does not already exist. Subsequent deployments will never overwrite an existing remote `.env`.

**Rollback Procedure:**
Every build tags the image with both `latest` and `mdbridge:<TAG>` (e.g. `mdbridge:90d8a43` or `mdbridge:90d8a43-dirty`) and transfers both tags to the NAS. Rollback only works for tags deployed with this script version. To roll back to a previous tag without rebuilding:
```bash
ssh user@192.168.50.174 "docker tag mdbridge:<TAG> mdbridge:latest && cd /srv/docker/mdbridge && docker compose up -d --force-recreate"
```

### 2. Configure Cloudflare Tunnel Public Hostname
In Cloudflare Zero Trust Dashboard, create the public hostname `md.opinasdeque.es` pointing to Nginx Proxy Manager **before** requesting the SSL certificate in NPM.

### 3. Configure Nginx Proxy Manager (NPM)
- Forward Hostname / IP: `mdbridge` (on external network `proxy-network`)
- Forward Port: `8000`
- SSL: Request Let's Encrypt certificate with "Force SSL" enabled.
- **Advanced Configuration** (Custom Nginx Configuration tab):
  ```nginx
  client_max_body_size 1100m;
  proxy_read_timeout 650s;
  proxy_send_timeout 650s;
  ```

### 4. Protect with Cloudflare Access
In Cloudflare Zero Trust, add an Access Application for `md.opinasdeque.es` before announcing or sharing the URL (configured with email OTP, Google OAuth, and optional Service Tokens for scripts).

### 5. Add Uptime Kuma Health Monitor
Add an HTTP monitor in Uptime Kuma targeting the internal container endpoint:
- URL: `http://mdbridge:8000/healthz` (with Uptime Kuma attached to `proxy-network`, since production publishes no host ports; or alternatively, a Docker exec health check)
- Interval: 60s
- Expected status: `200`

### 6. Verify Temp Directory Cleanliness
Confirm that request-scoped temporary files are deleted after conversions:
```bash
docker exec mdbridge ls -A /tmp
```
*(Should return empty output)*
