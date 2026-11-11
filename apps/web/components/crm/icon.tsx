import type { CSSProperties } from "react";
const paths = {
  trash: "M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7",
  history: "M3 11a9 9 0 1 1 3 7M3 4v7h7M12 7v5l3 2",
  refresh: "M20 7v5h-5M4 17v-5h5M6 6a8 8 0 0 1 14 6M4 12a8 8 0 0 0 14 6",
  edit: "m16 3 5 5M4 20l5-1L21 7l-5-5L4 14z",
  arrowUp: "M12 20V4m-7 7 7-7 7 7",
  microphone:
    "M12 15a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v7a3 3 0 0 0 3 3ZM5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8",
  paperclip: "m8 12 7-7a3 3 0 0 1 4 4L9 19a5 5 0 0 1-7-7L13 1M6 14l8-8",
  send: "m21 3-7 18-4-8-8-4 19-6ZM10 13l11-10",
  stop: "M6 6h12v12H6z",
  download: "M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5",

  settings: "M4 6h4m4 0h8M4 12h8m4 0h4M4 18h4m4 0h8M8 3v6M16 9v6M8 15v6",
  connections: "M8 8h8v8H8zM12 2v6M12 16v6M2 12h6M16 12h6",
  home: "M3 11 12 3l9 8M5 9v11h5v-6h4v6h5V9",
  board: "M3 4h5v16H3zM10 4h5v10h-5zM17 4h4v13h-4z",
  people:
    "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M16 4a4 4 0 0 1 0 8M22 21v-2a4 4 0 0 0-3-3.87M13 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0",
  check: "m5 12 4 4L19 6",
  task: "M9 5H5v16h15V5h-4M9 3h7v5H9zM9 15l2 2 5-6",
  plus: "M12 5v14M5 12h14",
  close: "m6 6 12 12M6 18 18 6",
  search: "m21 21-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0",
  arrow: "M5 19 19 5M5 5h14v14",
  logout: "M9 21H3V3h6M14 8l5 4-5 4M8 12h11",
  calendar: "M4 5h16v16H4zM8 2v6M16 2v6M4 10h16",
  menu: "M4 6h16M4 12h16M4 18h16",
  list: "M9 6h12M9 12h12M9 18h12M3 6h1M3 12h1M3 18h1",
  phone: "M7 3H3c0 10 8 18 18 18v-4l-5-2-2 2a15 15 0 0 1-7-7l2-2z",
  message: "M21 11a9 9 0 0 1-9 9 11 11 0 0 1-4-1l-6 2 2-6a9 9 0 1 1 17-4",
  eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0",
  chevron: "m9 5 7 7-7 7",
  leaf: "M20 3C8 3 3 7 3 13a7 7 0 0 0 7 7c7 0 10-8 10-17ZM5 19l9-9",
} as const;
export function Icon({
  name,
  size = 18,
  style,
}: {
  name: keyof typeof paths;
  size?: number;
  style?: CSSProperties;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={style}
    >
      <path d={paths[name]} />
    </svg>
  );
}
