import type { NextRequest } from "next/server";

const rules: [RegExp, string[]][] = [
  [/^auth\/login$/, ["POST"]],
  [/^auth\/logout$/, ["POST"]],
  [/^auth\/session$/, ["GET"]],
  [/^workspace$/, ["GET"]],
  [/^control\/catalog$/, ["GET"]],
  [/^control\/items$/, ["POST"]],
  [/^control\/items\/[0-9a-f-]{36}$/, ["PATCH"]],
  [/^control\/items\/[0-9a-f-]{36}\/run$/, ["POST"]],
  [
    /^control\/connections\/(hermes|zernio|facebook|instagram|tiktok|whatsapp|telegram)$/,
    ["PATCH"],
  ],
  [/^sara\/(status|skills)$/, ["GET"]],
  [/^sara\/conversations$/, ["GET", "POST"]],
  [/^sara\/conversations\/[0-9a-f-]{36}$/, ["PATCH"]],
  [/^sara\/conversations\/[0-9a-f-]{36}\/messages$/, ["GET", "POST"]],
  [/^sara\/attachments$/, ["POST"]],
  [/^sara\/attachments\/[0-9a-f-]{36}\/content$/, ["GET"]],
  [/^hermes\/status$/, ["GET"]],
  [/^hermes\/(chat|actions)$/, ["POST"]],
  [/^hermes\/proposals\/[0-9a-f-]{36}\/(approve|reject)$/, ["POST"]],
  [/^social\/settings$/, ["GET", "POST"]],
  [/^social\/(sync|complete)$/, ["POST"]],
  [/^social\/mcp\/status$/, ["GET"]],
  [/^social\/mcp\/(start|complete|check|disconnect)$/, ["POST"]],
  [
    /^social\/connect\/(facebook|instagram|tiktok|whatsapp|telegram)$/,
    ["POST"],
  ],
  [/^contacts$/, ["POST"]],
  [/^contacts\/[0-9a-f-]{36}$/, ["PATCH"]],
  [/^deals\/[0-9a-f-]{36}$/, ["PATCH"]],
  [/^deals\/[0-9a-f-]{36}\/activities$/, ["GET"]],
  [/^deals\/[0-9a-f-]{36}\/notes$/, ["POST"]],
  [/^tasks$/, ["POST"]],
  [/^tasks\/[0-9a-f-]{36}$/, ["PATCH"]],
];
const privateHeaders = { "Cache-Control": "no-store, private" };
const fail = (status: number, detail: string) =>
  Response.json({ detail }, { status, headers: privateHeaders });

async function boundedResult(upstream: Response, maximum: number) {
  const reader = upstream.body?.getReader();
  const chunks: Uint8Array[] = [];
  let length = 0;
  if (reader)
    while (true) {
      const part = await reader.read();
      if (part.done) break;
      length += part.value.byteLength;
      if (length > maximum) {
        await reader.cancel();
        return null;
      }
      chunks.push(part.value);
    }
  const result = new Uint8Array(length);
  let offset = 0;
  for (const part of chunks) {
    result.set(part, offset);
    offset += part.byteLength;
  }
  return result;
}

async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  const endpoint = path.join("/");
  if (
    !rules.some(
      ([pattern, methods]) =>
        pattern.test(endpoint) && methods.includes(request.method),
    )
  ) {
    return fail(404, "not_found");
  }
  let query = "";
  const sara = endpoint.startsWith("sara/");
  if (sara) {
    const params = new URL(request.url).searchParams;
    const paginated =
      request.method === "GET" &&
      (endpoint === "sara/conversations" ||
        /^sara\/conversations\/[0-9a-f-]{36}\/messages$/.test(endpoint));
    if (
      [...params.keys()].some((key) => key !== "before") ||
      params.getAll("before").length > 1 ||
      (params.size && !paginated)
    )
      return fail(422, "invalid_input");
    const cursor = params.get("before");
    if (cursor !== null) {
      if (
        !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(
          cursor,
        )
      )
        return fail(422, "invalid_input");
      query = `?before=${cursor}`;
    }
  }
  const base = process.env.API_BASE_URL;
  if (!base) return fail(503, "crm_not_configured");
  const mutation = request.method !== "GET";
  if (
    mutation &&
    (!process.env.CRM_ORIGIN ||
      request.headers.get("origin") !== process.env.CRM_ORIGIN)
  ) {
    return fail(403, "invalid_origin");
  }
  let body: Uint8Array | undefined;
  if (mutation) {
    const definitionWrite =
      (request.method === "POST" && endpoint === "control/items") ||
      (request.method === "PATCH" &&
        /^control\/items\/[0-9a-f-]{36}$/.test(endpoint));
    const bodyLimit =
      endpoint === "sara/attachments"
        ? 768 * 1024
        : definitionWrite
          ? 65536
          : 16384;
    if (!request.headers.get("content-type")?.startsWith("application/json"))
      return fail(415, "invalid_content_type");
    const reader = request.body?.getReader();
    const chunks: Uint8Array[] = [];
    let length = 0;
    if (reader) {
      while (true) {
        const part = await reader.read();
        if (part.done) break;
        length += part.value.byteLength;
        if (length > bodyLimit) {
          await reader.cancel();
          return fail(413, "request_too_large");
        }
        chunks.push(part.value);
      }
    }
    body = new Uint8Array(length);
    let offset = 0;
    for (const chunk of chunks) {
      body.set(chunk, offset);
      offset += chunk.length;
    }
  }
  const headers = new Headers({ "Content-Type": "application/json" });
  for (const name of ["origin", "x-csrf-token"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const session =
    request.cookies.get("__Host-jardines_session") ??
    request.cookies.get("jardines_session");
  if (session) headers.set("cookie", `${session.name}=${session.value}`);
  const timeout =
    /^sara\/conversations\/[0-9a-f-]{36}\/messages$/.test(endpoint) && mutation
      ? 95000
      : endpoint === "sara/attachments"
        ? 35000
        : endpoint === "hermes/chat"
          ? 90000
          : endpoint.startsWith("hermes/") ||
              /^control\/items\/[0-9a-f-]{36}\/run$/.test(endpoint)
            ? 30000
            : endpoint.startsWith("social/mcp/")
              ? 20000
              : 8000;
  try {
    const upstream = await fetch(`${base}/crm/${endpoint}${query}`, {
      method: request.method,
      headers,
      body: body as BodyInit | undefined,
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(timeout),
    });
    const resultHeaders = new Headers({
      ...privateHeaders,
      "Content-Type": "application/json",
    });
    for (const cookie of upstream.headers.getSetCookie())
      resultHeaders.append("Set-Cookie", cookie);
    const retry = upstream.headers.get("retry-after");
    if (retry) resultHeaders.set("Retry-After", retry);
    if (sara) {
      const download =
        /^sara\/attachments\/[0-9a-f-]{36}\/content$/.test(endpoint) &&
        upstream.ok;
      const type = upstream.headers
        .get("content-type")
        ?.split(";")[0]
        .toLowerCase();
      const media = [
        "text/plain",
        "text/markdown",
        "text/csv",
        "application/pdf",
        "audio/webm",
        "audio/ogg",
        "audio/mpeg",
        "audio/mp3",
        "audio/wav",
        "audio/x-wav",
        "audio/mp4",
      ];
      if (
        (download && !media.includes(type ?? "")) ||
        (!download && type !== "application/json")
      )
        return fail(502, "invalid_upstream_response");
      const raw = await boundedResult(
        upstream,
        download ? 512 * 1024 : 2 * 1024 * 1024,
      );
      if (!raw) return fail(502, "upstream_response_too_large");
      resultHeaders.set("X-Content-Type-Options", "nosniff");
      if (download) {
        resultHeaders.set("Content-Type", type!);
        const disposition =
          upstream.headers.get("content-disposition") ?? "attachment";
        if (
          disposition.length > 512 ||
          !/^attachment(?:;|$)/i.test(disposition) ||
          /[\r\n]/.test(disposition)
        )
          return fail(502, "invalid_upstream_response");
        resultHeaders.set("Content-Disposition", disposition);
        resultHeaders.set("Content-Security-Policy", "sandbox");
      }
      return new Response(raw as BodyInit, {
        status: upstream.status,
        headers: resultHeaders,
      });
    }
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: resultHeaders,
    });
  } catch {
    return fail(503, "service_unavailable");
  }
}
export { proxy as GET, proxy as POST, proxy as PATCH };
