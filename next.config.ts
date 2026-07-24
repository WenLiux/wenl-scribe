import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async headers() {
    return [{
      source: "/:path*",
      headers: [{
        key: "Content-Security-Policy",
        value: "frame-src 'self' https://player.bilibili.com",
      }],
    }];
  },
};

export default nextConfig;
