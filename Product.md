# PRODUCT.md — MyMarkItDown

> Self-hosted document → Markdown converter for feeding LLMs. Runs on the home NAS, reachable from any computer through Cloudflare Tunnel. Built on Microsoft's [MarkItDown](https://github.com/microsoft/markitdown).

## 1. Problem

Before handing documents to an LLM (Claude, Codex, etc.), they need to be clean Markdown: headings, tables and lists preserved, no binary noise. MarkItDown does this well, but it's a Python CLI that has to be installed on every machine. I want one always-on service, on my own hardware, that I can use from any computer with just a browser.

## 2. Goal

From any computer, I open `https://md.opinasdeque.es`, pick a **local input folder**, pick a **local output folder**, press *Convert*, and get one `.md` file per supported document written into the output folder — mirroring the input folder structure. Nothing is kept on the server.

## 3. Users

- **Primary:** me (Pablo), on my MacBook and on work/other machines.
- **Secondary:** possibly family members later. No multi-tenant features needed.
- Access is gated by **Cloudflare Access** (email OTP / Google), not by the app.

## 4. Key architectural fact (read this first)

The container runs on the NAS. **A server can never read or write a folder on the client's computer.** The "read a local folder / write to a local folder" behaviour must therefore happen **in the browser**:

- **Primary path — File System Access API** (`showDirectoryPicker`): the browser reads files from the chosen input folder, uploads them one by one to the API, receives Markdown, and writes `.md` files directly into the chosen output folder. Supported in Chromium browsers (Chrome, Edge, Brave, Arc) on desktop.
- **Fallback path — upload + ZIP download:** for Safari/Firefox (no directory write access), the user selects/drag-drops a folder or files (`<input webkitdirectory>`), and receives a single `.zip` of the generated `.md` files, preserving relative paths.
- **Scripting path — HTTP API:** the same `/api/convert` endpoint is usable with `curl` or a tiny CLI script, so batch jobs can run without a browser (see §8).

The server is a **stateless converter**: bytes in → Markdown out.

## 5. Scope

### In scope (v1)

| Category | Extensions |
|---|---|
| PDF | `.pdf` |
| Word | `.docx` |
| PowerPoint | `.pptx` |
| Excel | `.xlsx`, `.xls` |
| Data / text | `.csv`, `.json`, `.xml`, `.txt`, `.md` |
| Web | `.html`, `.htm` |
| E-books | `.epub` |
| Outlook | `.msg` |

### Explicitly out of scope

- **Images** (`.jpg`, `.png`, `.heic`, `.gif`, `.webp`, `.tiff`, …) — rejected client-side and server-side.
- **Audio/video** (MarkItDown can transcribe audio — disabled).
- **URLs / YouTube / web fetching** — the server never fetches remote content.
- **LLM-based image captioning / OCR** (MarkItDown's `llm_client` option) — not configured.
- **ZIP archives as input** — skip in v1 (they can smuggle images and zip bombs).
- **Legacy `.doc` / `.ppt`** — MarkItDown does not support them. Report as "unsupported" in v1. Possible v2: LibreOffice headless pre-conversion to `.docx`/`.pptx` in a sidecar.
- User accounts, history, storage of documents or results.

## 6. Functional requirements

### Web UI
1. **Pick input folder** → app scans it recursively and shows a table: relative path, size, status (`supported` / `skipped: image` / `skipped: unsupported`).
2. **Pick output folder** (Chromium) — or the UI explains the ZIP fallback when the API is unavailable.
3. **Options:**
   - Recurse into subfolders (default: on)
   - Skip files whose `.md` already exists and is newer than the source (default: on) — enables incremental re-runs
   - Add YAML front matter with source metadata (default: on), e.g.
     ```yaml
     ---
     source_file: reports/Q3_risk.xlsx
     source_size_bytes: 482113
     converted_at: 2026-10-12T10:15:00Z
     converter: markitdown 0.x.y
     ---
     ```
4. **Convert** → files processed with a small client-side concurrency (default 2), progress bar, per-file status (`done`, `failed: <reason>`, `skipped`).
5. **Output naming:** `input/sub/Report.pdf` → `output/sub/Report.md`. If two sources collide (`Report.pdf` + `Report.docx` in the same folder), name them `Report.pdf.md` and `Report.docx.md`.
6. **Summary** at the end: converted / skipped / failed counts, plus a downloadable `_conversion_log.json` written to the output folder.
7. A **"Copy to clipboard"** button on single-file conversions (handy for pasting straight into a chat).

### API
- `POST /api/convert` — multipart, one file per request. Returns `text/markdown` (or JSON `{markdown, warnings, converter_version}` with `?format=json`).
- `GET /api/formats` — list of accepted extensions (UI uses it as the source of truth).
- `GET /healthz` — liveness, used by Docker healthcheck and Uptime Kuma.

## 7. Non-functional requirements

| Area | Requirement |
|---|---|
| **Privacy** | No document or Markdown is written to disk on the server beyond a request-scoped temp file, deleted in a `finally`. No content in logs — only filename hash, size, duration, status. |
| **Limits** | Max upload per file: **95 MB** (Cloudflare free plan rejects request bodies >100 MB). Per-file conversion timeout: 120 s. |
| **Resources** | NAS is a Ryzen 3500U / 12 GB RAM shared with other services → container `cpus: 2`, `mem_limit: 2g`, server-side concurrency 2 (queue the rest). |
| **Security** | Validate extension **and** magic bytes; reject images even if renamed. Run as non-root, read-only root FS, `tmpfs` for `/tmp`. No outbound network needed at runtime. |
| **Availability** | `restart: unless-stopped`, Docker healthcheck on `/healthz`. |
| **Platform** | Image built for `linux/amd64` (dev machine is Apple Silicon). |
| **Footprint** | Image < 600 MB if possible; install only the MarkItDown extras needed (`pdf`, `docx`, `pptx`, `xlsx`, `xls`, `outlook`), not `[all]`. |

## 8. Usage examples

```bash
# Single file
curl -sS -F "file=@Q3_report.pdf" https://md.opinasdeque.es/api/convert -o Q3_report.md

# Through Cloudflare Access with a service token (for scripts)
curl -sS \
  -H "CF-Access-Client-Id: $CF_ID" -H "CF-Access-Client-Secret: $CF_SECRET" \
  -F "file=@Q3_report.pdf" https://md.opinasdeque.es/api/convert -o Q3_report.md
```

An optional `scripts/mdbridge-batch.sh` (or Python) mirrors a local folder into an output folder via the API — same naming rules as the UI.

## 9. Deployment

- Host: OMV NAS `192.168.50.174`, Docker Compose stack `mdbridge`.
- Network: joins the existing external Docker network `proxy-network`; **no host port published** in production.
- Ingress: Cloudflare Tunnel public hostname `md.opinasdeque.es` → Nginx Proxy Manager → `mdbridge:8000`.
- Protection: Cloudflare Access application on `md.opinasdeque.es` (allow-list: my emails; optional service token for scripts).
- NPM proxy host: set `client_max_body_size 100m;` and raise `proxy_read_timeout` to 150 s.

## 10. Success criteria

- [ ] A folder with mixed PDF / DOCX / XLSX / PPTX / images converts end-to-end from Chrome on my MacBook; images are listed as skipped; output tree mirrors input.
- [ ] Same folder via Safari produces a correct ZIP.
- [ ] Re-running on the same folder skips unchanged files.
- [ ] A renamed `photo.jpg → photo.pdf` is rejected by the server.
- [ ] A 90 MB PDF converts; a 110 MB file fails with a clear message, not a hang.
- [ ] `docker exec` shows no leftover files in `/tmp` after a batch.
- [ ] Unauthenticated request to `md.opinasdeque.es` is stopped by Cloudflare Access.

## 11. Roadmap (not v1)

- LibreOffice sidecar for `.doc` / `.ppt` / `.rtf` / `.odt`.
- Expose MarkItDown's MCP server (`markitdown-mcp`) so Claude/Codex can call the converter directly as a tool.
- Optional chunking output (split long docs by heading into multiple `.md` files sized for context windows).
- Azure Document Intelligence backend for scanned PDFs (MarkItDown supports it) — only if needed.
