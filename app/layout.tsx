import type { Metadata } from "next";
import { BRAND_COPY } from "./brand";
import "./globals.css";

export const metadata: Metadata = {
  title: "留文 · WENL SCRIBE｜本地视频转录与内容总结",
  description: `${BRAND_COPY.slogan}。粘贴 B 站链接，在本地生成完整逐字稿与结构化总结。`,
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
