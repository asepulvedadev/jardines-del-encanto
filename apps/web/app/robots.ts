import type { MetadataRoute } from "next";
import { publicOrigin } from "../lib/public-seo";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: ["/crm", "/login", "/api/", "/health"],
    },
    sitemap: `${publicOrigin}/sitemap.xml`,
  };
}
