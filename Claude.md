# CLAUDE.md — MyMarKItDown

Instructions for AI coding agents (Claude Code, Codex, etc.) working in this repo.
**Read `PRODUCT.md` first** — it defines what to build and what is out of scope. This file defines *how*.

> Codex looks for `AGENTS.md`. Keep this file as the single source: `ln -s CLAUDE.md AGENTS.md`.

## Project in one paragraph

A stateless web service that converts uploaded documents (PDF, Office, CSV, HTML, EPUB, MSG…) to Markdown using Microsoft's `markitdown` Python library. Images and audio are rejected. A static single-page UI uses the browser **File System Access API** to read a local input folder and write `.md` files to a local output folder; browsers without it get a ZIP download. Runs as a Docker container on an x86 OpenMediaVault NAS, exposed via Cloudflare Tunnel → Nginx Proxy Manager, protected by Cloudflare Access.

## Stack (do not change without asking)

| Layer | Choice |
|---|---|
| Language | Python 3.12 |
| API | FastAPI + Uvicorn |
| Conversion | `markitdown` with extras `[pdf,docx,pptx,xlsx,xls,outlook]` — **not** `[all]` |
| File-type sniffing | `python-magic` (libmagic) or `filetype` |
| Frontend | Plain HTML + vanilla JS (ES modules) + one small CSS file, served by FastAPI as static files. **No build step, no framework.** `JSZip` from cdnjs for the ZIP fallback. |
| Tests | `pytest`, `httpx` (`TestClient`) |
| Lint/format | `ruff` (lint + format) |
| Deps | `uv` with `pyproject.toml` + `uv.lock` (pin `markitdown` to an exact version) |
| Container | Multi-stage `python:3.12-slim`, non-root user, `linux/amd64` |

## Repo layout

```
mdbridge/
├── CLAUDE.md / AGENTS.md (symlink)
├── PRODUCT.md
├── README.md
├── pyproject.toml
├── uv.lock
├── Dockerfile
├── docker-compose.yml          # production (NAS)
├── docker-compose.dev.yml      # local dev: publishes 8000, bind-mounts src
├── .env.example
├── app/
│   ├── main.py                 # FastAPI app, routes, static mount
│   ├── config.py               # pydantic-settings, all env vars
│   ├── converter.py            # thin wrapper around MarkItDown
│   ├── validation.py           # extension + magic-byte allow/deny lists
│   ├── frontmatter.py
│   └── static/
│       ├── index.html
│       ├── app.js              # folder picking, queue, writing files
│       ├── fs-access.js        # File System Access API helpers
│       ├── zip-fallback.js
│       └── styles.css
├── scripts/
│   └── mdbridge-batch.sh       # folder → folder via the API (curl)
└── tests/
    ├── fixtures/               # tiny sample.pdf/.docx/.xlsx/.pptx/.csv/.html, fake.pdf (really a JPEG)
    ├── test_api.py
    ├── test_validation.py
    └── test_converter.py
```

## Configuration (env vars, all with defaults in `config.py`)

| Var | Default | Notes |
|---|---|---|
| `MAX_UPLOAD_MB` | `95` | Cloudflare free plan caps bodies at 100 MB |
| `CONVERT_TIMEOUT_S` | `120` | per file |
| `MAX_CONCURRENCY` | `2` | asyncio semaphore around conversions |
| `ENABLE_FRONTMATTER_DEFAULT` | `true` | UI default |
| `LOG_LEVEL` | `INFO` | |
| `ROOT_PATH` | `""` | in case it's ever served under a sub-path |

## Implementation rules

### Conversion (`converter.py`)
- Instantiate `MarkItDown(enable_plugins=False)` **once** at startup. Never pass `llm_client`, `docintel_endpoint`, or URLs.
- Convert from a stream or a request-scoped temp file with an **explicit extension hint**; never call `convert()` with anything that could be interpreted as a URI.
- Run conversion in a worker thread (`anyio.to_thread.run_sync` / `run_in_threadpool`) guarded by the concurrency semaphore and `CONVERT_TIMEOUT_S`. If the timeout hits, return 504 with a clear message.
- Temp files: `tempfile.NamedTemporaryFile(dir="/tmp", delete=False)` + `os.unlink` in `finally`. Nothing else touches disk.
- Expose `converter_version` = installed `markitdown` version (via `importlib.metadata`).

### Validation (`validation.py`)
- Single allow-list of extensions (see PRODUCT.md §5) — `GET /api/formats` returns it; the frontend must not hard-code its own copy.
- Check **both** extension and magic bytes. Deny any `image/*`, `audio/*`, `video/*` MIME regardless of extension. Deny `.zip` in v1 (note: `.docx/.xlsx/.pptx/.epub` *are* zips — validate them by extension + zip container, don't blanket-reject `application/zip`).
- Reject over-size uploads early (check `Content-Length`, and enforce while streaming).
- Error responses are JSON: `{"error": "<code>", "detail": "<human message>"}` with codes `unsupported_type`, `image_rejected`, `too_large`, `timeout`, `conversion_failed`.

### API
- `POST /api/convert` (multipart field `file`, query `frontmatter=true|false`, `format=md|json`)
- `GET /api/formats`, `GET /healthz`
- Never log file contents or Markdown. Log: sha256 prefix of filename, size, extension, duration ms, status.

### Frontend
- Feature-detect `window.showDirectoryPicker`. If present → folder-to-folder mode. Else → `<input type="file" webkitdirectory multiple>` + ZIP download.
- Walk the input directory recursively; build the plan table before converting; filter by `/api/formats`.
- Write outputs with `getDirectoryHandle(..., {create: true})` to mirror subfolders. Request `readwrite` permission on the output handle once, up front.
- Incremental mode: skip when the target `.md` exists and its `lastModified` ≥ source `lastModified`.
- Collision rule: if two sources in one folder share a stem, use `<name>.<ext>.md` for both.
- Client concurrency default 2; retry once on network error / 5xx; no retry on 4xx.
- Write `_conversion_log.json` to the output root at the end.
- Must work at phone width without breaking, but desktop is the real target.
- Fetches use `credentials: "include"` so the Cloudflare Access cookie is sent.

### Docker
- Multi-stage: builder installs deps with `uv`; runtime copies the venv. Install `libmagic1` in runtime.
- `USER app` (uid 1000), `HEALTHCHECK` hitting `/healthz`.
- `docker-compose.yml` (production):
  - `image: mdbridge:latest`, `container_name: mdbridge`, `restart: unless-stopped`
  - `networks: [proxy-network]` (declared `external: true`) — **no `ports:`**
  - `read_only: true`, `tmpfs: ["/tmp:size=512m"]`, `security_opt: ["no-new-privileges:true"]`
  - `cpus: "2.0"`, `mem_limit: 2g`
- Build on the Mac with `docker buildx build --platform linux/amd64 -t mdbridge:latest .`
- Redeploy = `docker compose up -d --force-recreate` (a plain `docker restart` does **not** pick up a new image).

## Infrastructure context (for docs and README, don't automate)

- NAS: OpenMediaVault 7, Ryzen 3500U, 12 GB RAM, `192.168.50.174`, shared with other services → be frugal.
- Ingress chain: Cloudflare Tunnel (`nas-tunnel`) → Nginx Proxy Manager → `mdbridge:8000` on `proxy-network`.
- Order matters: create the Cloudflare Tunnel public hostname `md.opinasdeque.es` **before** requesting the cert in NPM.
- NPM advanced config for this host: `client_max_body_size 100m; proxy_read_timeout 150s; proxy_send_timeout 150s;`
- Add a Cloudflare Access application for `md.opinasdeque.es` before announcing the URL anywhere.
- Add an Uptime Kuma HTTP monitor on `/healthz` (internal URL).

## Commands

```bash
uv sync                                   # install
uv run uvicorn app.main:app --reload      # dev server on :8000
uv run pytest -q                          # tests
uv run ruff check . && uv run ruff format --check .
docker compose -f docker-compose.dev.yml up --build
```

## Definition of done (every PR)

1. `ruff` clean, `pytest` green.
2. New behaviour has a test; fixtures stay tiny (< 200 KB each, committed).
3. `test_api.py` covers: each supported type converts, image rejected, renamed JPEG rejected, oversize rejected, temp dir empty after requests.
4. README updated if env vars, endpoints, or deploy steps changed.
5. No new runtime dependency without stating why in the PR description.

## Don'ts

- Don't add a database, user accounts, or persistent storage.
- Don't enable MarkItDown plugins, LLM captioning, audio transcription, or URL fetching.
- Don't publish container ports in the production compose file.
- Don't add a JS framework or bundler.
- Don't install `markitdown[all]`.
- Don't silently change scope — if something in PRODUCT.md looks wrong, stop and ask.

## Suggested build order

1. `validation.py` + `converter.py` + tests (no web yet).
2. FastAPI endpoints + API tests.
3. Dockerfile + compose; verify on the Mac, then `linux/amd64` build.
4. Frontend: Chromium folder-to-folder path.
5. ZIP fallback.
6. `scripts/mdbridge-batch.sh`.
7. README with the NAS deploy runbook (Tunnel → NPM → Access → Uptime Kuma).
