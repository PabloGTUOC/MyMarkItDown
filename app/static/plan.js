/**
 * Pure functions for plan table classification, output naming collision rules,
 * and incremental conversion skip decisions.
 */

export const IMAGE_EXTENSIONS = new Set([
  ".jpg",
  ".jpeg",
  ".png",
  ".gif",
  ".webp",
  ".bmp",
  ".tiff",
  ".tif",
  ".heic",
  ".heif",
  ".ico",
  ".svg",
]);

/**
 * Extract lowercased file extension with leading dot, e.g. ".pdf".
 * Returns empty string if no extension.
 */
export function getExtension(filename) {
  const lastDot = filename.lastIndexOf(".");
  if (lastDot === -1 || lastDot === 0) return "";
  return filename.slice(lastDot).toLowerCase();
}

/**
 * Extract filename stem without extension.
 */
export function getStem(filename) {
  const lastDot = filename.lastIndexOf(".");
  if (lastDot === -1 || lastDot === 0) return filename;
  return filename.slice(0, lastDot);
}

/**
 * Split a relative path into [dirPath, basename].
 * E.g. "sub/folder/file.pdf" -> ["sub/folder", "file.pdf"]
 *      "file.pdf" -> ["", "file.pdf"]
 */
export function splitPath(relPath) {
  const lastSlash = relPath.lastIndexOf("/");
  if (lastSlash === -1) {
    return ["", relPath];
  }
  return [relPath.slice(0, lastSlash), relPath.slice(lastSlash + 1)];
}

/**
 * Classify a file into one of: 'supported', 'skipped: image', 'skipped: unsupported'.
 * @param {string} filename - The name or path of the file.
 * @param {string[]} allowedExtensions - Allow-list of extensions from /api/formats.
 * @returns {'supported' | 'skipped: image' | 'skipped: unsupported'}
 */
export function classifyFile(filename, allowedExtensions = []) {
  const ext = getExtension(filename);
  if (IMAGE_EXTENSIONS.has(ext)) {
    return "skipped: image";
  }

  const allowedSet = new Set(
    allowedExtensions.map((e) => (e.startsWith(".") ? e.toLowerCase() : `.${e.toLowerCase()}`))
  );

  if (allowedSet.has(ext)) {
    return "supported";
  }

  return "skipped: unsupported";
}

/**
 * Resolve target relative Markdown paths for an array of source relative paths.
 * Rule: input/sub/Report.pdf -> output/sub/Report.md.
 * If two sources in the same folder share a stem, use <name>.<ext>.md for both.
 * E.g. ["sub/Report.pdf", "sub/Report.docx"] ->
 *   { "sub/Report.pdf": "sub/Report.pdf.md", "sub/Report.docx": "sub/Report.docx.md" }
 *
 * @param {string[]} relPaths - List of relative source paths.
 * @returns {Record<string, string>} Mapping from source relPath to target relPath.
 */
export function resolveOutputNames(relPaths) {
  // 1. Group files by parent directory
  const byDir = new Map();
  for (const path of relPaths) {
    const [dir, basename] = splitPath(path);
    if (!byDir.has(dir)) {
      byDir.set(dir, []);
    }
    byDir.get(dir).push({ fullPath: path, basename });
  }

  const result = {};

  // 2. For each directory, count stem occurrences
  for (const [dir, files] of byDir.entries()) {
    const stemCounts = new Map();
    for (const item of files) {
      const stem = getStem(item.basename).toLowerCase();
      stemCounts.set(stem, (stemCounts.get(stem) || 0) + 1);
    }

    for (const item of files) {
      const stem = getStem(item.basename);
      const isCollision = (stemCounts.get(stem.toLowerCase()) || 0) > 1;

      const outName = isCollision ? `${item.basename}.md` : `${stem}.md`;
      const outPath = dir ? `${dir}/${outName}` : outName;
      result[item.fullPath] = outPath;
    }
  }

  return result;
}

/**
 * Determine if a file conversion should be skipped in incremental mode.
 * Skip when target exists and target lastModified >= source lastModified.
 *
 * @param {number} sourceLastModified - Unix timestamp in ms.
 * @param {number | null | undefined} targetLastModified - Unix timestamp in ms or null/undefined if missing.
 * @returns {boolean}
 */
export function shouldSkipUnchanged(sourceLastModified, targetLastModified) {
  if (targetLastModified == null) {
    return false;
  }
  return targetLastModified >= sourceLastModified;
}

/**
 * Strip the first path segment (the picked root directory name) from a webkitRelativePath.
 * E.g. "MyFolder/sub/file.pdf" -> "sub/file.pdf"
 *      "MyFolder/file.pdf"     -> "file.pdf"
 *      "file.pdf"              -> "file.pdf"
 *
 * @param {string} webkitRelativePath
 * @returns {string}
 */
export function stripRootFolder(webkitRelativePath) {
  if (!webkitRelativePath) return "";
  const firstSlash = webkitRelativePath.indexOf("/");
  if (firstSlash === -1) {
    return webkitRelativePath;
  }
  return webkitRelativePath.slice(firstSlash + 1);
}

/**
 * Filter items by recurse option. If recurse is false, keep only top-level items.
 *
 * @template T
 * @param {T[]} items - Array of path strings or objects containing a `relPath` string property.
 * @param {boolean} recurse - Whether to include nested subfolder files.
 * @returns {T[]}
 */
export function filterByRecurse(items, recurse = true) {
  if (recurse) return items;
  return items.filter((item) => {
    const path = typeof item === "string" ? item : item.relPath;
    return !path.includes("/");
  });
}

/**
 * Generate zip filename formatted as markdown-YYYYMMDD-HHMMSS.zip.
 *
 * @param {Date} date
 * @returns {string}
 */
export function generateZipFilename(date = new Date()) {
  const pad = (n) => String(n).padStart(2, "0");
  const y = date.getFullYear();
  const m = pad(date.getMonth() + 1);
  const d = pad(date.getDate());
  const hh = pad(date.getHours());
  const mm = pad(date.getMinutes());
  const ss = pad(date.getSeconds());
  return `markdown-${y}${m}${d}-${hh}${mm}${ss}.zip`;
}

