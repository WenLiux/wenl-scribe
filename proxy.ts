import { NextResponse } from "next/server";

export function proxy() {
  const response = NextResponse.next();
  response.headers.set(
    "Content-Security-Policy",
    "frame-src 'self' https://player.bilibili.com",
  );
  return response;
}

export const config = {
  matcher: "/:path*",
};
