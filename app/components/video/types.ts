export type BilibiliVideoInfo = {
  platform: "bilibili";
  bvid: string;
  page: number;
  sourceUrl: string;
  title?: string;
  author?: string;
  duration?: number;
};

export type VideoSeekRequest = {
  seconds: number;
  autoplay: boolean;
  version: number;
};
