import type { MetadataRoute } from "next";
import { deploymentTitle } from "@/lib/deployment-title";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: deploymentTitle(process.env.NEXT_PUBLIC_APP_ENVIRONMENT),
    short_name: deploymentTitle(process.env.NEXT_PUBLIC_APP_ENVIRONMENT),
    description: "Identity, secure access and automation in one platform.",
    start_url: "/",
    display: "standalone",
    background_color: "#0B1220",
    theme_color: "#0B1220",
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/icons/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}

