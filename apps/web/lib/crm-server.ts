import "server-only";
import { cookies } from "next/headers";

export async function crmSession() {
  const jar = await cookies();
  const token =
    jar.get("__Host-jardines_session") ?? jar.get("jardines_session");
  if (!token) return null;
  const base = process.env.API_BASE_URL;
  if (!base) throw new Error("CRM service is not configured");
  const response = await fetch(`${base}/crm/auth/session`, {
    headers: { Cookie: `${token.name}=${token.value}` },
    cache: "no-store",
    signal: AbortSignal.timeout(8000),
  });
  if (response.status === 401) return null;
  if (!response.ok) throw new Error("CRM service is unavailable");
  return response.json() as Promise<{
    user: { username: string; role: string };
    csrf_token: string;
  }>;
}

export async function crmWorkspace() {
  const base = process.env.API_BASE_URL;
  if (!base) throw new Error("CRM service is not configured");
  const jar = await cookies();
  const token =
    jar.get("__Host-jardines_session") ?? jar.get("jardines_session");
  const response = await fetch(`${base}/crm/workspace`, {
    headers: { Cookie: token ? `${token.name}=${token.value}` : "" },
    cache: "no-store",
    signal: AbortSignal.timeout(8000),
  });
  if (!response.ok) throw new Error("CRM workspace is unavailable");
  return response.json();
}
