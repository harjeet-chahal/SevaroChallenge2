import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The Docker build sets BUILD_STANDALONE=1 to emit a self-contained server in
  // .next/standalone. Off locally, where `next start` would warn about it.
  output: process.env.BUILD_STANDALONE === "1" ? "standalone" : undefined,
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
