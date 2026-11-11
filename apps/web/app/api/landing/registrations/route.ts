const headers = { "Cache-Control": "no-store, private" };
const fail = (status: number, detail: string) =>
  Response.json(
    { detail },
    {
      status,
      headers: {
        ...headers,
        ...(status === 429 ? { "Retry-After": "600" } : {}),
      },
    },
  );

export async function POST(request: Request) {
  const origin = process.env.CRM_ORIGIN;
  if (!origin || request.headers.get("origin") !== origin)
    return fail(403, "invalid_origin");
  if (
    request.headers
      .get("content-type")
      ?.split(";", 1)[0]
      .trim()
      .toLowerCase() !== "application/json"
  )
    return fail(415, "invalid_content_type");
  const reader = request.body?.getReader();
  const chunks: Uint8Array[] = [];
  let length = 0;
  if (reader) {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > 2048) {
        await reader.cancel();
        return fail(413, "request_too_large");
      }
      chunks.push(value);
    }
  }
  if (!process.env.API_BASE_URL) return fail(503, "capture_unavailable");
  const body = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.length;
  }
  try {
    const response = await fetch(
      `${process.env.API_BASE_URL}/public/registrations`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", Origin: origin },
        body,
        cache: "no-store",
        credentials: "omit",
        redirect: "error",
        signal: AbortSignal.timeout(10000),
      },
    );
    if (!response.ok) {
      const status = [403, 409, 413, 415, 422, 429].includes(response.status)
        ? response.status
        : 503;
      return fail(
        status,
        status === 429
          ? "capture_throttled"
          : status === 422
            ? "invalid_input"
            : "capture_unavailable",
      );
    }
    const result = await response.json();
    if (
      typeof result.code !== "string" ||
      !/^JDE-[A-F0-9]{12}$/.test(result.code)
    )
      return fail(502, "invalid_capture_response");
    return Response.json({ code: result.code }, { status: 201, headers });
  } catch {
    return fail(503, "capture_unavailable");
  }
}
