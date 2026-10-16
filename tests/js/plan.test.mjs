import test from "node:test";
import assert from "node:assert/strict";
import {
  classifyFile,
  filterByRecurse,
  generateZipFilename,
  getExtension,
  getStem,
  resolveOutputNames,
  shouldSkipUnchanged,
  splitPath,
  stripRootFolder,
} from "../../app/static/plan.js";

const FORMATS = [
  ".pdf",
  ".docx",
  ".pptx",
  ".xlsx",
  ".xls",
  ".csv",
  ".json",
  ".xml",
  ".txt",
  ".md",
  ".html",
  ".htm",
  ".epub",
  ".msg",
];

test("classifyFile correctly identifies formats", () => {
  // Supported
  assert.equal(classifyFile("doc.pdf", FORMATS), "supported");
  assert.equal(classifyFile("folder/doc.DOCX", FORMATS), "supported");
  assert.equal(classifyFile("data.csv", FORMATS), "supported");
  assert.equal(classifyFile("sheet.xlsx", FORMATS), "supported");

  // Images
  assert.equal(classifyFile("photo.jpg", FORMATS), "skipped: image");
  assert.equal(classifyFile("photo.JPEG", FORMATS), "skipped: image");
  assert.equal(classifyFile("diagram.png", FORMATS), "skipped: image");
  assert.equal(classifyFile("icon.svg", FORMATS), "skipped: image");
  assert.equal(classifyFile("banner.webp", FORMATS), "skipped: image");

  // Unsupported
  assert.equal(classifyFile("archive.zip", FORMATS), "skipped: unsupported");
  assert.equal(classifyFile("binary.exe", FORMATS), "skipped: unsupported");
  assert.equal(classifyFile("legacy.doc", FORMATS), "skipped: unsupported");
  assert.equal(classifyFile("no_ext", FORMATS), "skipped: unsupported");
});

test("resolveOutputNames handles single files without collision", () => {
  const sources = ["Report.pdf", "sub/Data.xlsx", "sub/deep/Notes.docx"];
  const resolved = resolveOutputNames(sources);

  assert.equal(resolved["Report.pdf"], "Report.md");
  assert.equal(resolved["sub/Data.xlsx"], "sub/Data.md");
  assert.equal(resolved["sub/deep/Notes.docx"], "sub/deep/Notes.md");
});

test("resolveOutputNames handles collisions in the same directory", () => {
  const sources = [
    "sub/Report.pdf",
    "sub/Report.docx",
    "sub/Independent.xlsx",
  ];
  const resolved = resolveOutputNames(sources);

  // Colliding stem 'Report' in folder 'sub' gets <name>.<ext>.md
  assert.equal(resolved["sub/Report.pdf"], "sub/Report.pdf.md");
  assert.equal(resolved["sub/Report.docx"], "sub/Report.docx.md");
  // Non-colliding gets <stem>.md
  assert.equal(resolved["sub/Independent.xlsx"], "sub/Independent.md");
});

test("resolveOutputNames does not collide across different directories", () => {
  const sources = ["dirA/Report.pdf", "dirB/Report.docx"];
  const resolved = resolveOutputNames(sources);

  assert.equal(resolved["dirA/Report.pdf"], "dirA/Report.md");
  assert.equal(resolved["dirB/Report.docx"], "dirB/Report.md");
});

test("resolveOutputNames computed only over supported files avoids false collisions with images/unsupported", () => {
  const allScanned = [
    "sub/Report.pdf",
    "sub/Report.png",
    "sub/Report.zip",
    "sub/Data.xlsx",
  ];
  // Filter only files classified as 'supported'
  const supportedOnly = allScanned.filter(
    (path) => classifyFile(path, FORMATS) === "supported"
  );
  const resolved = resolveOutputNames(supportedOnly);

  // Since Report.png and Report.zip are not supported, Report.pdf is unique among supported files in 'sub'
  assert.equal(resolved["sub/Report.pdf"], "sub/Report.md");
  assert.equal(resolved["sub/Data.xlsx"], "sub/Data.md");
});

test("shouldSkipUnchanged decides based on timestamps", () => {
  const now = 1700000000000;

  // Target does not exist
  assert.equal(shouldSkipUnchanged(now, null), false);
  assert.equal(shouldSkipUnchanged(now, undefined), false);

  // Target is newer
  assert.equal(shouldSkipUnchanged(now, now + 5000), true);

  // Target has exact same timestamp
  assert.equal(shouldSkipUnchanged(now, now), true);

  // Target is older
  assert.equal(shouldSkipUnchanged(now, now - 5000), false);
});

test("stripRootFolder strips the first path segment from webkitRelativePath", () => {
  assert.equal(stripRootFolder("PickedFolder/sub/file.pdf"), "sub/file.pdf");
  assert.equal(stripRootFolder("PickedFolder/file.pdf"), "file.pdf");
  assert.equal(stripRootFolder("file.pdf"), "file.pdf");
  assert.equal(stripRootFolder(""), "");
});

test("filterByRecurse filters items based on recurse option", () => {
  const items = [
    { relPath: "root.pdf" },
    { relPath: "sub/nested.docx" },
    { relPath: "sub/deep/inner.xlsx" },
  ];

  // Recurse on keeps all items
  const withRecurse = filterByRecurse(items, true);
  assert.equal(withRecurse.length, 3);

  // Recurse off keeps only top-level items
  const withoutRecurse = filterByRecurse(items, false);
  assert.equal(withoutRecurse.length, 1);
  assert.equal(withoutRecurse[0].relPath, "root.pdf");

  // Works with string arrays as well
  const paths = ["root.pdf", "sub/nested.docx"];
  assert.deepEqual(filterByRecurse(paths, false), ["root.pdf"]);
});

test("generateZipFilename produces expected format", () => {
  const date = new Date(2026, 9, 12, 15, 30, 45); // Oct 12, 2026, 15:30:45
  const filename = generateZipFilename(date);
  assert.equal(filename, "markdown-20261012-153045.zip");
});
