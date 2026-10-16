/**
 * ZIP fallback mode for browsers without window.showDirectoryPicker (Safari, Firefox).
 */

const JSZIP_CDN_URL = "https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js";
let jszipPromise = null;

/**
 * Lazily load JSZip from cdnjs via a classic script tag if not already available.
 */
export function loadJSZip() {
  if (typeof window !== "undefined" && window.JSZip) {
    return Promise.resolve(window.JSZip);
  }

  if (jszipPromise) {
    return jszipPromise;
  }

  jszipPromise = new Promise((resolve, reject) => {
    const existingScript = document.querySelector(`script[src="${JSZIP_CDN_URL}"]`);
    if (existingScript) {
      existingScript.addEventListener("load", () => resolve(window.JSZip));
      existingScript.addEventListener("error", () => reject(new Error("Failed to load JSZip from CDN")));
      return;
    }

    const script = document.createElement("script");
    script.src = JSZIP_CDN_URL;
    script.async = true;
    script.onload = () => {
      if (window.JSZip) {
        resolve(window.JSZip);
      } else {
        reject(new Error("JSZip loaded but window.JSZip is undefined"));
      }
    };
    script.onerror = () => reject(new Error("Failed to load JSZip from CDN"));
    document.head.appendChild(script);
  });

  return jszipPromise;
}

/**
 * Trigger browser download of a Blob via an object URL, revoking the URL afterwards.
 */
export function triggerBlobDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/**
 * Create a pluggable ZIP output sink.
 */
export async function createZipSink() {
  const JSZipClass = await loadJSZip();
  const zip = new JSZipClass();

  return {
    type: "zip",
    async writeFile(relFilePath, content) {
      zip.file(relFilePath, content);
    },
    async finish(logJsonString) {
      if (logJsonString) {
        zip.file("_conversion_log.json", logJsonString);
      }
      return await zip.generateAsync({ type: "blob" });
    },
    download(blob, filename) {
      triggerBlobDownload(blob, filename);
    },
  };
}
