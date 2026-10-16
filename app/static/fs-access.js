/**
 * File System Access API helpers.
 */

import { splitPath } from "./plan.js";

/**
 * Check if the browser supports the File System Access API.
 */
export function isFileSystemAccessSupported() {
  return typeof window !== "undefined" && typeof window.showDirectoryPicker === "function";
}

/**
 * Open directory picker to select a folder.
 */
export async function pickDirectory() {
  if (!isFileSystemAccessSupported()) {
    throw new Error("File System Access API is not supported in this browser.");
  }
  return await window.showDirectoryPicker();
}

/**
 * Request readwrite permission on a directory handle up front.
 */
export async function verifyReadWritePermission(dirHandle) {
  const options = { mode: "readwrite" };
  if ((await dirHandle.queryPermission(options)) === "granted") {
    return true;
  }
  const status = await dirHandle.requestPermission(options);
  return status === "granted";
}

/**
 * Recursively scan a directory handle and yield { relPath, file, handle }.
 *
 * @param {FileSystemDirectoryHandle} dirHandle
 * @param {boolean} recurse
 * @param {string} prefix
 * @returns {AsyncGenerator<{ relPath: string, file: File, handle: FileSystemFileHandle }>}
 */
export async function* walkDirectory(dirHandle, recurse = true, prefix = "") {
  // Use entries() on directory handle
  for await (const [name, handle] of dirHandle.entries()) {
    const relPath = prefix ? `${prefix}/${name}` : name;
    if (handle.kind === "file") {
      const file = await handle.getFile();
      yield { relPath, file, handle };
    } else if (handle.kind === "directory" && recurse) {
      yield* walkDirectory(handle, recurse, relPath);
    }
  }
}

/**
 * Collect all scanned files into an array.
 */
export async function collectFiles(dirHandle, recurse = true) {
  const files = [];
  for await (const item of walkDirectory(dirHandle, recurse)) {
    files.push(item);
  }
  return files;
}

/**
 * Ensure nested subdirectories exist under a root handle with create: true.
 */
export async function ensureDirectoryPath(rootHandle, relDirPath) {
  let current = rootHandle;
  if (!relDirPath) return current;

  const parts = relDirPath.split("/").filter(Boolean);
  for (const part of parts) {
    current = await current.getDirectoryHandle(part, { create: true });
  }
  return current;
}

/**
 * Read the lastModified timestamp of an existing target file, or return null if it doesn't exist.
 */
export async function getTargetLastModified(rootHandle, relFilePath) {
  try {
    let current = rootHandle;
    const [dirPath, fileName] = splitPath(relFilePath);
    if (dirPath) {
      for (const part of dirPath.split("/").filter(Boolean)) {
        current = await current.getDirectoryHandle(part, { create: false });
      }
    }
    const fileHandle = await current.getFileHandle(fileName, { create: false });
    const file = await fileHandle.getFile();
    return file.lastModified;
  } catch {
    return null;
  }
}

/**
 * Write file contents (string or Blob/Uint8Array) to output directory handle.
 */
export async function writeFile(rootHandle, relFilePath, content) {
  const [dirPath, fileName] = splitPath(relFilePath);
  const targetDir = await ensureDirectoryPath(rootHandle, dirPath);
  const fileHandle = await targetDir.getFileHandle(fileName, { create: true });
  const writable = await fileHandle.createWritable();
  await writable.write(content);
  await writable.close();
}
