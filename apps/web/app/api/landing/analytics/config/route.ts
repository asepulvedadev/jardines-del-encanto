import { analyticsConfiguration } from "../../../../../lib/analytics-config";

export const dynamic = "force-dynamic";
export function GET() {
  return Response.json({ enabled: Boolean(analyticsConfiguration()) }, { headers: { "Cache-Control": "no-store, private" } });
}
