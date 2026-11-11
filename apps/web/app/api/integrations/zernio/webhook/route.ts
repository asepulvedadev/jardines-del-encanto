import type { NextRequest } from "next/server";

const headers = { "Cache-Control": "no-store" };
const fail = (status: number, detail: string) =>
  Response.json({ detail }, { status, headers });

// Public transport only: the API verifies the raw-body HMAC and profile ownership.
// Browser cookies, authorization and arbitrary forwarding destinations are prohibited.
export async function POST(request: NextRequest) {
  if (!request.headers.get("content-type")?.startsWith("application/json"))
    return fail(415, "invalid_content_type");
  if (!/^[a-f0-9]{64}$/i.test(request.headers.get("x-zernio-signature") ?? ""))
    return fail(400, "invalid_signature");
  const base = process.env.API_BASE_URL;
  if (!base) return fail(503, "service_unavailable");
  const chunks: Uint8Array[] = [];
  const reader = request.body?.getReader();
  let length = 0;
  if (reader) {
    while (true) {
      const part = await reader.read();
      if (part.done) break;
      length += part.value.byteLength;
      if (length > 256 * 1024) {
        await reader.cancel();
        return fail(413, "request_too_large");
      }
      chunks.push(part.value);
    }
  }
  const body = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.length;
  }
  const upstreamHeaders = new Headers({ "Content-Type": "application/json" });
  for (const name of ["x-zernio-signature", "x-zernio-event", "x-zernio-event-id"]) {
    const value = request.headers.get(name);
    if (value) upstreamHeaders.set(name, value);
  }
  try {
    const result = await fetch(`${base}/integrations/zernio/webhook`, {
      method: "POST", headers: upstreamHeaders, body,
      redirect: "error", cache: "no-store", signal: AbortSignal.timeout(4000),
    });
    return new Response(await result.text(), {
      status: result.status,
      headers: { ...headers, "Content-Type": "application/json" },
    });
  } catch {
    return fail(503, "service_unavailable");
  }
}
