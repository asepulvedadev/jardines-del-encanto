import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const read = (name) =>
  readFileSync(
    new URL(`../apps/web/components/crm/${name}`, import.meta.url),
    "utf8",
  );
test("Sara sends idempotent turns and never offers historical unresolved approval replay", () => {
  const source = read("sara-panel.tsx");
  assert.match(source, /crypto.randomUUID\(\)/);
  assert.match(source, /request_id/);
  assert.match(source, /resolvable !== false/);
  assert.match(source, /ActionProposals/);
  assert.match(source, /ActionResultDetails/);
  assert.doesNotMatch(
    source,
    /localStorage|sessionStorage|dangerouslySetInnerHTML/,
  );
});
test("voice capture remains bounded and releases resources without browser speech recognition", () => {
  const source = read("sara-audio.ts");
  assert.match(source, /60000/);
  assert.match(source, /512 \* 1024/);
  assert.match(source, /track.stop\(\)/);
  assert.doesNotMatch(source, /SpeechRecognition|speechSynthesis/);
});
test("Sara uses private server history and explicit note preview before upload", () => {
  const source = read("sara-panel.tsx");
  assert.match(source, /credentials: "same-origin"/);
  assert.match(source, /X-CSRF-Token/);
  assert.match(source, /AbortController/);
  assert.match(source, /Usar nota/);
  assert.match(source, /voice_available/);
  assert.match(source, /before=/);
  assert.match(source, /onManageSkills/);
});

import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
const require = createRequire(import.meta.url),
  cache = new Map();
const root = fileURLToPath(
  new URL("../apps/web/components/crm/", import.meta.url),
);
function load(name) {
  const path = resolve(root, name);
  if (cache.has(path)) return cache.get(path).exports;
  const module = { exports: {} };
  cache.set(path, module);
  const code = ts.transpileModule(readFileSync(path, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      jsx: ts.JsxEmit.ReactJSX,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const localRequire = (specifier) => {
    if (specifier.endsWith(".css")) return {};
    if (specifier === "next/navigation")
      return { useRouter: () => ({ replace() {}, refresh() {} }) };
    if (specifier.startsWith(".")) {
      const stem = resolve(dirname(path), specifier);
      for (const ext of [".tsx", ".ts"]) {
        try {
          readFileSync(stem + ext);
        } catch {
          continue;
        }
        return load(stem + ext);
      }
      throw Error(`Missing ${specifier}`);
    }
    return require(specifier);
  };
  new Function("require", "module", "exports", code)(
    localRequire,
    module,
    module.exports,
  );
  return module.exports;
}
const { mergeSaraMessages, saraUploadMime, saraFileBase64 } =
  load("sara-types.ts");
test("message pagination merges chronological history without duplicates and refreshes server state", () => {
  const old = { id: "b", created_at: "2026-11-11T11:00:00Z", state: "pending" };
  const fresh = { ...old, state: "completed" };
  const earlier = { id: "a", created_at: "2026-11-11T10:00:00Z" };
  assert.deepEqual(mergeSaraMessages([old], [earlier, fresh]), [
    earlier,
    fresh,
  ]);
});
test("uploads normalize only supported MIME/extension pairs and enforce decoded512KiB", async () => {
  assert.equal(
    saraUploadMime("nota.webm", "audio/webm;codecs=opus"),
    "audio/webm",
  );
  assert.equal(saraUploadMime("nota.mp3", "audio/mp3"), "audio/mpeg");
  assert.equal(saraUploadMime("nota.wav", "audio/x-wav"), "audio/wav");
  assert.equal(saraUploadMime("texto.md", "text/plain"), "text/markdown");
  assert.throws(() => saraUploadMime("page.html", "text/html"));
  assert.throws(() => saraUploadMime("fake.pdf", "text/html"));
  assert.equal(await saraFileBase64(new Blob(["hello"])), "aGVsbG8=");
  await assert.rejects(() =>
    saraFileBase64(new Blob([new Uint8Array(512 * 1024 + 1)])),
  );
  await assert.rejects(() => saraFileBase64(new Blob([])));
});
test("rendered historical proposals cannot replay approval and message content is escaped", () => {
  const { SaraMessageView } = load("sara-panel.tsx");
  const base = {
    id: "m",
    role: "assistant",
    content: "<script>unsafe</script>",
    created_at: "2026-11-11T10:00:00Z",
    state: "completed",
    attachments: [],
    results: [],
    proposals: [
      {
        id: "p",
        action: "crm.note.create",
        arguments: { body: "exact" },
        status: "pending",
        version: 1,
        resolvable: false,
      },
    ],
  };
  const html = renderToStaticMarkup(
    React.createElement(SaraMessageView, {
      message: base,
      csrf: "fixture",
      request: async () => {},
      onChanged: async () => {},
    }),
  );
  assert.match(html, /Propuesta no disponible en esta sesión/);
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /Aprobar acción exacta|Rechazar|<script>/);
  const live = renderToStaticMarkup(
    React.createElement(SaraMessageView, {
      message: {
        ...base,
        proposals: [{ ...base.proposals[0], resolvable: true }],
      },
      csrf: "fixture",
      request: async () => {},
      onChanged: async () => {},
    }),
  );
  assert.match(live, /Aprobar acción exacta/);
  assert.match(live, /Argumentos exactos/);
});
test("rendered chat offers server-backed history, labeled composer and no invented answer", () => {
  const { SaraPanel } = load("sara-panel.tsx");
  const html = renderToStaticMarkup(
    React.createElement(SaraPanel, {
      csrf: "fixture",
      onChanged: async () => {},
    }),
  );
  assert.match(html, /aria-label="Sara IA"/);
  assert.match(html, /role="log"/);
  assert.match(html, /Mensaje para Sara IA/);
  assert.match(html, /Skills del proyecto/);
  assert.match(html, /Consultar|Consultando/);
  assert.doesNotMatch(html, /SpeechRecognition|Llamar|Iniciar llamada/);
});
function fakeMedia() {
  const descriptors = {
    navigator: Object.getOwnPropertyDescriptor(globalThis, "navigator"),
    MediaRecorder: Object.getOwnPropertyDescriptor(globalThis, "MediaRecorder"),
    isSecureContext: Object.getOwnPropertyDescriptor(
      globalThis,
      "isSecureContext",
    ),
  };
  let stops = 0,
    permissions = 0;
  const tracks = [
    {
      stop() {
        stops++;
      },
    },
  ];
  const stream = { getTracks: () => tracks };
  const instances = [];
  class FakeRecorder {
    static isTypeSupported(mime) {
      return mime === "audio/webm;codecs=opus";
    }
    state = "inactive";
    constructor(_stream, options) {
      this.mime = options.mimeType;
      instances.push(this);
    }
    start() {
      this.state = "recording";
    }
    stop() {
      if (this.state === "inactive") return;
      this.state = "inactive";
      this.ondataavailable?.({
        data: new Blob(["fixture"], { type: this.mime }),
      });
      queueMicrotask(() => this.onstop?.());
    }
  }
  Object.defineProperty(globalThis, "isSecureContext", {
    value: true,
    configurable: true,
  });
  Object.defineProperty(globalThis, "MediaRecorder", {
    value: FakeRecorder,
    configurable: true,
  });
  Object.defineProperty(globalThis, "navigator", {
    value: {
      mediaDevices: {
        getUserMedia: async () => {
          permissions++;
          return stream;
        },
      },
    },
    configurable: true,
  });
  return {
    stream,
    instances,
    get stops() {
      return stops;
    },
    get permissions() {
      return permissions;
    },
    restore() {
      for (const [key, value] of Object.entries(descriptors)) {
        if (value) Object.defineProperty(globalThis, key, value);
        else delete globalThis[key];
      }
    },
  };
}
test("recording is local until explicit use and stops tracks on stop and oversize cancellation", async () => {
  const media = fakeMedia();
  const { SaraRecorder } = load("sara-audio.ts");
  const previews = [],
    errors = [];
  const capture = new SaraRecorder(
    (file) => previews.push(file),
    (error) => errors.push(error),
    () => {},
  );
  try {
    assert.equal(media.permissions, 0);
    await capture.start();
    assert.equal(media.permissions, 1);
    capture.stop();
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(media.stops, 1);
    assert.equal(previews.length, 1);
    assert.equal(previews[0].type, "audio/webm;codecs=opus");
    assert.equal(previews[0].name, "nota-de-voz.webm");
    const next = new SaraRecorder(
      (file) => previews.push(file),
      (error) => errors.push(error),
      () => {},
    );
    await next.start();
    media.instances
      .at(-1)
      .ondataavailable({ data: new Blob([new Uint8Array(512 * 1024 + 1)]) });
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(media.stops, 2);
    assert.equal(previews.length, 1);
    assert.match(errors[0], /512 KiB/);
    next.dispose();
  } finally {
    capture.dispose();
    media.restore();
  }
});
test("cancel while microphone permission is pending stops eventual stream and never previews", async () => {
  const media = fakeMedia();
  let resolvePermission;
  Object.defineProperty(globalThis, "navigator", {
    value: {
      mediaDevices: {
        getUserMedia: () =>
          new Promise((resolve) => {
            resolvePermission = resolve;
          }),
      },
    },
    configurable: true,
  });
  const { SaraRecorder } = load("sara-audio.ts");
  let previews = 0;
  const capture = new SaraRecorder(
    () => previews++,
    () => {},
    () => {},
  );
  try {
    const opening = capture.start();
    capture.cancel();
    resolvePermission(media.stream);
    await opening;
    assert.equal(media.stops, 1);
    assert.equal(previews, 0);
    assert.equal(media.instances.length, 0);
  } finally {
    capture.dispose();
    media.restore();
  }
});

test("stale conversation pages cannot erase a newly created conversation or rename", () => {
  const { mergeSaraConversations } = load("sara-types.ts");
  const old = {
    id: "a",
    title: "Original",
    updated_at: "2026-11-11T10:00:00Z",
  };
  const renamed = {
    ...old,
    title: "Renamed",
    updated_at: "2026-11-11T12:00:00Z",
  };
  const created = { id: "b", title: "New", updated_at: "2026-11-11T13:00:00Z" };
  assert.deepEqual(mergeSaraConversations([created, renamed], [old]), [
    created,
    renamed,
  ]);
});
test("recording automatically stops at60seconds and releases media", async () => {
  const media = fakeMedia();
  const { SaraRecorder } = load("sara-audio.ts");
  const originalTimeout = globalThis.setTimeout,
    originalClear = globalThis.clearTimeout;
  let limit,
    callback,
    previews = 0;
  globalThis.setTimeout = (fn, delay) => {
    callback = fn;
    limit = delay;
    return 1;
  };
  globalThis.clearTimeout = () => {};
  const capture = new SaraRecorder(
    () => previews++,
    () => {},
    () => {},
  );
  try {
    await capture.start();
    assert.equal(limit, 60000);
    callback();
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(media.stops, 1);
    assert.equal(previews, 1);
  } finally {
    capture.dispose();
    globalThis.setTimeout = originalTimeout;
    globalThis.clearTimeout = originalClear;
    media.restore();
  }
});
