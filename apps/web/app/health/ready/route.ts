export const dynamic = "force-dynamic";
export async function GET() {
  try {
    const response = await fetch(`${process.env.API_BASE_URL ?? "http://127.0.0.1:8000"}/health/ready`, {
      cache: "no-store", signal: AbortSignal.timeout(4000),
    });
    if (!response.ok) throw new Error("Backend unavailable");
    return Response.json({ status: "ok" });
  } catch {
    return Response.json({ status: "unavailable" }, { status: 503 });
  }
}
