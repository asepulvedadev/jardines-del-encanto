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
  assert.match(source, /saraSkillQuery/);
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
  assert.match(html, /Escribe \$ para ver skills/);
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

test("Sara follows the reference's single chat with named modal history and one attachment entry", () => {
  const { SaraPanel } = load("sara-panel.tsx");
  const html = renderToStaticMarkup(
    React.createElement(SaraPanel, {
      csrf: "fixture",
      onChanged: async () => {},
    }),
  );
  assert.match(
    html,
    /<dialog[^>]*class="sara-history-dialog"[^>]*aria-labelledby="sara-history-title"/,
  );
  assert.doesNotMatch(html, /<aside/);
  assert.match(html, /aria-label="Historial de conversaciones"/);
  assert.match(html, /aria-label="Nueva conversación"/);
  assert.equal((html.match(/type="file"/g) ?? []).length, 1);
  assert.doesNotMatch(html, /sara-title-form/);
});

test("composer keyboard preserves multiline and IME input while new chats need no title form", () => {
  const source = read("sara-panel.tsx");
  assert.match(source, /event\.nativeEvent\.isComposing/);
  assert.match(source, /event\.shiftKey/);
  assert.match(source, /requestSubmit\(\)/);
  assert.doesNotMatch(source, /setCreating|setNewTitle/);
});

test("tool results collapse together but live proposal consequences remain separate", () => {
  const { SaraMessageView } = load("sara-panel.tsx");
  const html = renderToStaticMarkup(
    React.createElement(SaraMessageView, {
      message: {
        id: "reference-message",
        role: "assistant",
        content: "Resultado real",
        created_at: "2026-11-11T10:00:00Z",
        state: "completed",
        attachments: [],
        results: [{ action: "crm.workspace", result: { contacts: [] } }],
        proposals: [],
      },
      csrf: "fixture",
      request: async () => {},
      onChanged: async () => {},
    }),
  );
  assert.match(html, /<details class="sara-activity">/);
  assert.match(html, /Actividad de Sara/);
});

test("composer exposes one focus boundary and activity retains a44px keyboard/touch target", () => {
  const css = read("sara.css");
  assert.match(
    css,
    /\.crm-shell \.sara-composer textarea:focus-visible\s*\{[^}]*outline: none/s,
  );
  assert.match(css, /\.sara-composer:focus-within\s*\{[^}]*box-shadow:/s);
  assert.match(
    css,
    /\.sara-workspace \.sara-activity > summary\s*\{[^}]*min-height: 44px/s,
  );
});

test("dollar skill picker recognizes only the active token and replaces it without sending", () => {
  const { saraSkillQuery, saraInsertSkill } = load("sara-types.ts");
  assert.deepEqual(saraSkillQuery("Usa $ven después", 8), {
    start: 4,
    end: 8,
    query: "ven",
  });
  assert.deepEqual(saraSkillQuery("$", 1), { start: 0, end: 1, query: "" });
  assert.equal(saraSkillQuery("Precio$13", 9), null);
  assert.equal(saraSkillQuery("$[Ventas] ", 10), null);
  assert.equal(saraSkillQuery("Texto normal", 12), null);
  assert.deepEqual(
    saraInsertSkill(
      "Usa $ven después",
      { start: 4, end: 8, query: "ven" },
      "Ventas",
    ),
    {
      text: "Usa $[Ventas]  después",
      caret: 14,
    },
  );
  assert.equal(
    saraInsertSkill("$", { start: 0, end: 1, query: "" }, "x]\n[evil").text,
    "$[x   evil] ",
  );
});

test("skills management is absent from the top toolbar and history has confirmed deletion", () => {
  const { SaraPanel } = load("sara-panel.tsx");
  const html = renderToStaticMarkup(
    React.createElement(SaraPanel, {
      csrf: "fixture",
      onChanged: async () => {},
    }),
  );
  assert.doesNotMatch(html, /aria-label="Ver skills"|sara-skills-dialog/);
  assert.match(html, /Borrar conversación/);
  assert.match(html, /Cancelar borrado/);
  assert.match(read("sara-panel.tsx"), /role="listbox"/);
});

test("Sara audio is an explicit bounded proposal control without playback on render", () => {
  const { SaraVoiceOutput } = load("sara-voice-output.tsx");
  let requests = 0;
  const props = {
    text: "Respuesta de Sara",
    request: async () => {
      requests++;
      throw Error("No render requests allowed");
    },
    onChanged: async () => {},
  };
  const html = renderToStaticMarkup(
    React.createElement(SaraVoiceOutput, props),
  );
  assert.match(html, /Proponer audio de esta respuesta con ElevenLabs/);
  assert.match(html, /Crear audio/);
  assert.doesNotMatch(html, /<audio|autoplay|<script/);
  assert.equal(requests, 0);
  for (const text of ["", " ", "x".repeat(1501)]) {
    assert.equal(
      renderToStaticMarkup(
        React.createElement(SaraVoiceOutput, { ...props, text }),
      ),
      "",
    );
  }
  assert.equal(requests, 0);
});

test("outgoing bubble appears before confirmation and reconciles only by exact server ID", () => {
  const { saraOutgoingMessage, saraVisibleMessages } = load("sara-types.ts");
  const payload = {
    request_id: "request-one",
    message: "Consulta mis clientes",
    attachment_ids: ["file-one"],
  };
  const draft = {
    text: payload.message,
    attachments: [{ id: "file-one", filename: "nota.webm", kind: "audio" }],
  };
  const outgoing = saraOutgoingMessage(payload, draft, "2026-11-14T12:00:00Z");
  draft.attachments.length = 0;
  assert.equal(outgoing.content, payload.message);
  assert.equal(outgoing.attachments.length, 1);
  assert.equal(outgoing.state, "pending");
  const existing = {
    ...outgoing,
    id: "unrelated-same-text",
    request_id: "other-request",
  };
  assert.deepEqual(saraVisibleMessages([existing], outgoing), [
    existing,
    outgoing,
  ]);
  const confirmed = { ...outgoing, id: "database-message" };
  assert.deepEqual(saraVisibleMessages([confirmed], outgoing, confirmed.id), [
    confirmed,
  ]);
  assert.deepEqual(saraVisibleMessages([], outgoing, confirmed.id), [outgoing]);
  assert.deepEqual(saraVisibleMessages([existing]), [existing]);
});

test("Sara working feedback shows only confirmed activity without raw tool arguments", () => {
  const { SaraWorking } = load("sara-working.tsx");
  const html = renderToStaticMarkup(
    React.createElement(SaraWorking, {
      progress: {
        phase: "claimed",
        activities: [
          {
            id: "a",
            label: "Consultar clientes y pipeline",
            outcome: "proposal",
          },
          { id: "b", label: "Consultar actividad", outcome: "failed" },
        ],
      },
      unavailable: false,
    }),
  );
  assert.match(html, /role="status"/);
  assert.match(html, /Sara está trabajando/);
  assert.match(html, /Consultar clientes y pipeline/);
  assert.match(html, /Requiere aprobación/);
  assert.match(html, /No se pudo completar/);
  assert.doesNotMatch(html, /JSON|<pre|Aplicado|Paso 1/);
  const sending = renderToStaticMarkup(
    React.createElement(SaraWorking, { unavailable: false }),
  );
  assert.match(sending, /Enviando tu mensaje/);
  assert.doesNotMatch(sending, /Consultar clientes/);
});

test("lost acknowledgements reconcile through persisted request identity and clear only the matching restored draft", () => {
  const {
    saraOutgoingMessage,
    saraVisibleMessages,
    saraDraftAfterConfirmation,
    saraHistoryConfirmsTurn,
  } = load("sara-types.ts");
  const draft = { text: "Hola Sara", attachments: [] };
  const payload = {
    request_id: "same-request",
    message: draft.text,
    attachment_ids: [],
  };
  const outgoing = saraOutgoingMessage(payload, draft, "2026-11-14T12:00:00Z");
  const user = { ...outgoing, id: "database-user", state: "completed" };
  const assistant = {
    ...user,
    id: "database-assistant",
    role: "assistant",
    content: "Respuesta",
  };
  assert.deepEqual(saraVisibleMessages([user, assistant], outgoing), [
    user,
    assistant,
  ]);
  assert.equal(
    saraHistoryConfirmsTurn([user, assistant], payload.request_id),
    true,
  );
  assert.equal(
    saraHistoryConfirmsTurn(
      [{ ...user, state: "pending" }, assistant],
      payload.request_id,
    ),
    false,
  );
  assert.equal(saraHistoryConfirmsTurn([user], payload.request_id), false);
  assert.equal(
    saraHistoryConfirmsTurn([user, assistant], "different-request"),
    false,
  );
  assert.deepEqual(saraDraftAfterConfirmation(draft, payload), {
    text: "",
    attachments: [],
  });
  const edited = { ...draft, text: "Otro mensaje" };
  assert.equal(saraDraftAfterConfirmation(edited, payload), edited);
  const attached = { ...draft, attachments: [{ id: "new-file" }] };
  assert.equal(saraDraftAfterConfirmation(attached, payload), attached);
});
