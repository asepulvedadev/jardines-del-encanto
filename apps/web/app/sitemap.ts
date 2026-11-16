import type { MetadataRoute } from "next";
import { buyerGuidePath, publicOrigin } from "../lib/public-seo";

export default function sitemap(): MetadataRoute.Sitemap {
  // No invented last-modified timestamp or non-public application routes.
  return [
    {
      url: `${publicOrigin}/`,
      images: [
        `${publicOrigin}/media/porteria-actual-1280.webp`,
        `${publicOrigin}/media/vias-actuales-1280.webp`,
      ],
    },
    {
      url: `${publicOrigin}${buyerGuidePath}`,
      images: [`${publicOrigin}/media/aerial-1920.webp`],
    },
  ];
}
