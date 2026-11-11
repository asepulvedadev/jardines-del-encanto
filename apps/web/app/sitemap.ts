import type { MetadataRoute } from "next";
import { buyerGuidePath, publicOrigin } from "../lib/public-seo";

export default function sitemap(): MetadataRoute.Sitemap {
  // No invented last-modified timestamp or non-public application routes.
  return [
    { url: `${publicOrigin}/` },
    { url: `${publicOrigin}${buyerGuidePath}` },
  ];
}
