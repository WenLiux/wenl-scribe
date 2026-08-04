import type { ReactNode, SVGProps } from "react";

export type IconName = "arrow-left" | "arrow-right" | "check" | "close" | "play" | "warning";

type IconProps = Omit<SVGProps<SVGSVGElement>, "name"> & {
  name: IconName;
  size?: number;
  strokeWidth?: number;
};

export function Icon({ name, size = 16, strokeWidth = 1.8, className, ...props }: IconProps) {
  const common = {
    fill: "none",
    stroke: "currentColor",
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    strokeWidth,
  };

  let content: ReactNode;
  switch (name) {
    case "arrow-left":
      content = <><path d="M19 12H5" {...common} /><path d="m11 6-6 6 6 6" {...common} /></>;
      break;
    case "arrow-right":
      content = <><path d="M5 12h14" {...common} /><path d="m13 6 6 6-6 6" {...common} /></>;
      break;
    case "check":
      content = <path d="m5 12 4 4L19 6" {...common} />;
      break;
    case "close":
      content = <><path d="m6 6 12 12" {...common} /><path d="m18 6-12 12" {...common} /></>;
      break;
    case "play":
      content = <path d="m8 5 11 7-11 7V5Z" fill="currentColor" stroke="none" />;
      break;
    case "warning":
      content = <><circle cx="12" cy="12" r="9" {...common} /><path d="M12 7v5" {...common} /><path d="M12 16h.01" {...common} /></>;
      break;
  }

  return (
    <svg
      {...props}
      className={className ? `wenlIcon ${className}` : "wenlIcon"}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
    >
      {content}
    </svg>
  );
}
