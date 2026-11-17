export const dynamic = "force-dynamic";

const GROUP_URL =
  "https://chat.whatsapp.com/FiK8zZOYcj75lggiCfsNaq?s=cl&p=i&iam=2";

export function GET() {
  return new Response(null, {
    status: 302,
    headers: {
      Location: GROUP_URL,
      "Cache-Control": "no-store",
      "X-Robots-Tag": "noindex, nofollow",
      "Referrer-Policy": "no-referrer",
    },
  });
}

export const HEAD = GET;
