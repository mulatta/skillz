#!/usr/bin/env node
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function arg(name) {
  const idx = process.argv.indexOf(name);
  if (idx < 0 || idx + 1 >= process.argv.length) return null;
  return process.argv[idx + 1];
}

const webRoot = path.resolve(arg("--web-root") || ".");
const outPath = path.resolve(
  arg("--output") || path.join(__dirname, "shape-index.json"),
);
const manifestPath = path.resolve(
  arg("--manifest") || path.join(__dirname, "index-manifest.json"),
);
const version = arg("--drawio-version") || "unknown";
const expectedPath = arg("--expected") ? path.resolve(arg("--expected")) : null;
const appPath = path.join(webRoot, "js", "app.min.js");
const resourceLedger = [];
const errors = [];
const registrations = [];
const captures = [];

function fail(message) {
  throw new Error(message);
}

function resolveLocalUrl(url) {
  let raw = String(url || "");
  if (/^https?:\/\//i.test(raw)) {
    fail(`remote request forbidden: ${raw}`);
  }
  raw = raw.split("#")[0].split("?")[0];
  if (!raw) raw = "/";
  if (raw.startsWith("/")) raw = raw.slice(1);
  const resolved = path.resolve(webRoot, decodeURIComponent(raw));
  const rootWithSep = webRoot.endsWith(path.sep) ? webRoot : webRoot + path.sep;
  if (resolved !== webRoot && !resolved.startsWith(rootWithSep)) {
    fail(`path escapes web root: ${url}`);
  }
  return resolved;
}

function readLocal(url) {
  const file = resolveLocalUrl(url);
  resourceLedger.push({ url: String(url), file });
  if (!fs.existsSync(file)) fail(`resource missing: ${url} -> ${file}`);
  return fs.readFileSync(file, "utf8");
}

function installXHR(window) {
  window.XMLHttpRequest = function XMLHttpRequest() {
    this.readyState = 0;
    this.status = 0;
    this.responseText = "";
    this.responseXML = null;
    this._method = "GET";
    this._url = "";
  };
  window.XMLHttpRequest.prototype.open = function open(method, url) {
    this._method = method;
    this._url = url;
  };
  window.XMLHttpRequest.prototype.send = function send() {
    try {
      if (this._method !== "GET")
        fail(`unsupported XHR method: ${this._method}`);
      this.responseText = readLocal(this._url);
      this.status = 200;
      this.readyState = 4;
      try {
        this.responseXML = new window.DOMParser().parseFromString(
          this.responseText,
          "text/xml",
        );
      } catch {
        this.responseXML = null;
      }
      if (this.onreadystatechange) this.onreadystatechange();
      if (this.onload) this.onload();
    } catch (err) {
      errors.push(err.message);
      this.status = 500;
      this.readyState = 4;
      if (this.onreadystatechange) this.onreadystatechange();
      if (this.onerror) this.onerror(err);
      throw err;
    }
  };
  window.XMLHttpRequest.prototype.setRequestHeader =
    function setRequestHeader() {};
  window.XMLHttpRequest.prototype.abort = function abort() {};
  window.XMLHttpRequest.prototype.getAllResponseHeaders =
    function getAllResponseHeaders() {
      return "";
    };
  window.XMLHttpRequest.prototype.getResponseHeader =
    function getResponseHeader() {
      return null;
    };
  window.XMLHttpRequest.prototype.overrideMimeType =
    function overrideMimeType() {};
}

function normalizeTags(value) {
  const seen = new Set();
  const result = [];
  String(value || "")
    .toLowerCase()
    .replace(/[/,();=#.]/g, " ")
    .split(/\s+/)
    .forEach((token) => {
      if (token.length >= 2 && !seen.has(token)) {
        seen.add(token);
        result.push(token);
      }
    });
  return result;
}

function normalizeLibrary(value) {
  if (value == null) return null;
  if (typeof value === "string") return value;
  if (typeof value === "object") {
    for (const key of ["id", "lib", "library", "title", "name"]) {
      if (value[key]) return String(value[key]);
    }
  }
  return null;
}

function deriveTitle(style, fallback) {
  if (fallback) return String(fallback);
  for (const re of [
    /shape=mxgraph\.[^;]+\.([^;]+)/,
    /resIcon=mxgraph\.[^;]+\.([^;]+)/,
  ]) {
    const m = String(style || "").match(re);
    if (m)
      return m[1]
        .replace(/[_-]/g, " ")
        .replace(/\b\w/g, (c) => c.toUpperCase());
  }
  return "Shape";
}

function sha256(input) {
  return createHash("sha256").update(input).digest("hex");
}

function compareText(left, right) {
  return left < right ? -1 : left > right ? 1 : 0;
}

function stableStringify(value) {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function matchesQuery(entry, query) {
  const haystack = new Set([
    ...entry.tags,
    ...normalizeTags(entry.title),
    ...entry.libraries.map((lib) => lib.toLowerCase()),
  ]);
  return query.split(/\s+/).every((term) => haystack.has(term));
}

function hasRemoteImage(entry) {
  const content = `${entry.style}\n${entry.templateXml || ""}`;
  return (
    /image=(?:https?:|https?%3a|\/\/)/i.test(content) ||
    /(?:src|xlink:href)=["'](?:https?:|\/\/)/i.test(content)
  );
}

function checkExpected(manifest) {
  if (!expectedPath) return;
  const expected = JSON.parse(fs.readFileSync(expectedPath, "utf8"));
  const actual = {
    drawioVersion: manifest.drawioVersion,
    entryCount: manifest.entriesAfterDedup,
    indexSha256: manifest.indexSha256,
    registrations: manifest.registrations,
    capturedItems: manifest.capturedItems,
    kindCounts: manifest.kindCounts,
  };
  for (const [key, expectedValue] of Object.entries(expected)) {
    if (!(key in actual)) fail(`unsupported baseline field: ${key}`);
    const actualValue = actual[key];
    if (stableStringify(actualValue) !== stableStringify(expectedValue))
      fail(
        `baseline mismatch for ${key}: expected ${stableStringify(expectedValue)}, got ${stableStringify(actualValue)}`,
      );
  }
}

function cellXml(window, graph, cells) {
  if (!graph || typeof graph.encodeCells !== "function") {
    fail("cannot encode composite shape cells");
  }
  try {
    return window.mxUtils.getXml(graph.encodeCells(cells));
  } catch (err) {
    fail(`encodeCells failed: ${err.message}`);
  }
}

function main() {
  if (!fs.existsSync(appPath)) fail(`missing app.min.js: ${appPath}`);
  const dom = new JSDOM(
    "<!doctype html><html><head></head><body></body></html>",
    {
      url: "https://app.diagrams.net/?dev=1&test=1",
      pretendToBeVisual: true,
      runScripts: "dangerously",
      beforeParse(window) {
        installXHR(window);
        window.mxBasePath = "/mxgraph/src";
        window.mxLoadResources = false;
        window.mxForceIncludes = false;
        window.mxLoadStylesheets = false;
        window.urlParams = { dev: "1", test: "1" };
        window.STENCIL_PATH = "/stencils";
        window.GRAPH_IMAGE_PATH = "/img";
        window.IMAGE_PATH = "/images";
        window.STYLE_PATH = "/styles";
        window.RESOURCES_PATH = "/resources";
        window.DRAWIO_BASE_URL = "https://app.diagrams.net";
        window.DRAWIO_SERVER_URL = "https://app.diagrams.net";
        window.DRAWIO_LOG_URL = "";
        window.navigator.serviceWorker = undefined;
      },
    },
  );
  const w = dom.window;
  if (w.HTMLCanvasElement && w.HTMLCanvasElement.prototype) {
    w.HTMLCanvasElement.prototype.getContext = function getContext() {
      return null;
    };
    w.HTMLCanvasElement.prototype.toDataURL = function toDataURL() {
      return "data:image/png;base64,";
    };
  }
  w.eval(fs.readFileSync(appPath, "utf8"));
  for (const name of ["Sidebar", "Graph", "Editor", "mxCell", "mxGeometry"]) {
    if (typeof w[name] === "undefined") fail(`missing global ${name}`);
  }
  for (const name of [
    "addEntry",
    "createItem",
    "initPalettes",
    "updateSearchIndex",
  ]) {
    if (typeof w.Sidebar.prototype[name] !== "function")
      fail(`missing Sidebar.${name}`);
  }

  const container = w.document.createElement("div");
  w.document.body.appendChild(container);
  const themes = {};
  const defaultXml = readLocal("/styles/default.xml");
  const themeDoc = new w.DOMParser().parseFromString(defaultXml, "text/xml");
  themes[w.Graph.prototype.defaultThemeName] = themeDoc.documentElement;
  const graph = new w.Graph(container, null, null, null, themes);
  const editor = new w.Editor(false, null, null, graph);
  const sidebar = Object.create(w.Sidebar.prototype);

  sidebar.editorUi = {
    editor,
    container,
    isOffline() {
      return true;
    },
    createTemporaryGraph(stylesheet) {
      return w.Graph.createOffscreenGraph(stylesheet);
    },
    addListener() {},
    fireEvent() {},
    getServiceName() {
      return "draw.io";
    },
    getBaseUrl() {
      return "https://app.diagrams.net";
    },
    getLibraryExpanded() {
      return true;
    },
    formatEnabled: true,
    handleError(err) {
      throw err;
    },
  };
  sidebar.taglist = {};
  sidebar.currentSearchEntryLibrary = null;
  sidebar.shapetags = {};
  sidebar.customEntries = null;
  sidebar.appendCustomLibraries = false;
  sidebar.addStencilsToIndex = false;
  sidebar.styleToLibs = {};
  sidebar.defaultImageWidth = 80;
  sidebar.defaultImageHeight = 80;
  sidebar.palettes = {};
  sidebar.graph = graph;
  sidebar.container = w.document.createElement("div");
  sidebar.wrapper = w.document.createElement("div");
  sidebar.container.appendChild(sidebar.wrapper);
  sidebar.initialDefaultVertexStyle = graph
    .getStylesheet()
    .getDefaultVertexStyle() || { fontSize: 12 };
  sidebar.initialDefaultEdgeStyle =
    graph.getStylesheet().getDefaultEdgeStyle() || {};

  sidebar.showPalettes = function showPalettes() {};
  sidebar.showEntries = function showEntries() {};
  sidebar.addSearchPalette = function addSearchPalette() {};
  sidebar.appendChild = function appendChild() {};
  sidebar.addFoldingHandler = function addFoldingHandler(_elt, _div, onInit) {
    if (onInit) onInit(w.document.createElement("div"));
  };
  sidebar.createTitle = function createTitle(title) {
    const elt = w.document.createElement("a");
    elt.textContent = title || "";
    return elt;
  };

  const originalAddEntry = w.Sidebar.prototype.addEntry;
  w.Sidebar.prototype.addEntry = function addEntry(tags, factory) {
    registrations.push({
      tags: String(tags || ""),
      factory,
      library: normalizeLibrary(this.currentSearchEntryLibrary),
    });
    return originalAddEntry.apply(this, arguments);
  };
  w.Sidebar.prototype.createItem = function createItem(
    cells,
    title,
    showLabel,
    showTitle,
    width,
    height,
  ) {
    const cellList = Array.isArray(cells) ? cells : [];
    captures.push({
      cells: cellList,
      title: title || "",
      width: width || 0,
      height: height || 0,
      graph: this.graph,
    });
    return w.document.createElement("a");
  };

  try {
    if (w.Sidebar.prototype.tagIndex)
      sidebar.addTagIndex(w.Graph.decompress(w.Sidebar.prototype.tagIndex));
    sidebar.initPalettes();
    sidebar.updateSearchIndex();
  } catch (err) {
    fail(`palette initialization failed: ${err.message}`);
  }

  const registrationCount = registrations.length;
  let executed = 0;
  for (const reg of registrations) {
    try {
      const before = captures.length;
      reg.factory();
      executed += 1;
      if (captures.length === before)
        fail(`factory produced no capture for tags: ${reg.tags}`);
      for (const capture of captures.slice(before)) {
        capture.tags = reg.tags;
        capture.library = reg.library;
      }
    } catch (err) {
      fail(`factory failed for tags ${reg.tags}: ${err.message}`);
    }
  }

  const merged = new Map();
  for (const capture of captures) {
    const cells = capture.cells;
    if (!cells.length) fail("capture has no cells");
    const primary = cells[0];
    const kind =
      cells.length === 1 && primary.edge
        ? "edge"
        : cells.length === 1 && primary.vertex
          ? "vertex"
          : "template";
    const style = cells.length === 1 ? String(primary.style || "") : "";
    const templateXml =
      kind === "template" ? cellXml(w, capture.graph, cells) : null;
    const keyMaterial = JSON.stringify({
      kind,
      style,
      templateXml,
      width: capture.width,
      height: capture.height,
    });
    const id = `sha256:${sha256(keyMaterial)}`;
    const title = deriveTitle(
      style,
      capture.title || (primary.value ? String(primary.value) : ""),
    );
    const tags = new Set([
      ...normalizeTags(capture.tags),
      ...normalizeTags(title),
      ...normalizeTags(style),
    ]);
    const libraries = new Set(capture.library ? [String(capture.library)] : []);
    if (merged.has(id)) {
      const old = merged.get(id);
      tags.forEach((tag) => old.tags.add(tag));
      libraries.forEach((lib) => old.libraries.add(lib));
    } else {
      merged.set(id, {
        id,
        kind,
        title,
        tags,
        libraries,
        style,
        width: Math.round(
          capture.width || (primary.geometry && primary.geometry.width) || 0,
        ),
        height: Math.round(
          capture.height || (primary.geometry && primary.geometry.height) || 0,
        ),
        templateXml,
      });
    }
  }

  const entries = [...merged.values()].map((entry) => ({
    ...entry,
    tags: [...entry.tags].sort(),
    libraries: [...entry.libraries].sort(),
  }));
  entries.sort(
    (a, b) => compareText(a.title, b.title) || compareText(a.id, b.id),
  );
  if (entries.length < 5000) fail(`too few entries: ${entries.length}`);
  const canaries = [
    "rectangle",
    "decision",
    "uml actor",
    "bpmn task",
    "aws lambda",
    "azure function",
    "gcp compute",
    "kubernetes pod",
    "cisco router",
    "pid valve",
    "electrical resistor",
  ];
  for (const query of canaries) {
    if (!entries.some((entry) => matchesQuery(entry, query)))
      fail(`missing canary query: ${query}`);
  }
  if (entries.some(hasRemoteImage))
    fail("remote image URL found in shape entry");
  if (errors.length) fail(`collector errors: ${errors.join("; ")}`);

  const kindCounts = {};
  const libraryCounts = {};
  for (const entry of entries) {
    kindCounts[entry.kind] = (kindCounts[entry.kind] || 0) + 1;
    for (const library of entry.libraries)
      libraryCounts[library] = (libraryCounts[library] || 0) + 1;
  }

  const index = { schemaVersion: 1, drawioVersion: version, entries };
  const raw = `${stableStringify(index)}\n`;
  const manifest = {
    schemaVersion: 1,
    builder: "jsdom-addEntry-createItem",
    drawioVersion: version,
    registrations: registrationCount,
    executedFactories: executed,
    capturedItems: captures.length,
    entriesAfterDedup: entries.length,
    kindCounts: Object.fromEntries(Object.entries(kindCounts).sort()),
    libraryCounts: Object.fromEntries(Object.entries(libraryCounts).sort()),
    canaries: Object.fromEntries(canaries.map((query) => [query, true])),
    resources: { requested: resourceLedger.length, failed: 0, remote: 0 },
    complete: true,
    indexSha256: sha256(raw),
  };
  checkExpected(manifest);
  fs.writeFileSync(outPath, raw);
  fs.writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
  dom.window.close();
}

try {
  main();
} catch (err) {
  console.error(err && err.stack ? err.stack : String(err));
  process.exit(1);
}
