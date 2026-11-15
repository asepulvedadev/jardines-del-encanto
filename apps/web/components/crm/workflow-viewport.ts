export type Viewport = { x: number; y: number; zoom: number };
export type Point = { x: number; y: number };
export const NODE_WIDTH = 268;
export const NODE_HEIGHT = 88;

export function zoomAt(view: Viewport, zoom: number, anchor: Point): Viewport {
  const next = Math.max(0.1, Math.min(2, zoom));
  const ratio = next / view.zoom;
  return {
    x: anchor.x - (anchor.x - view.x) * ratio,
    y: anchor.y - (anchor.y - view.y) * ratio,
    zoom: next,
  };
}

export function fitViewport(
  nodes: { position: Point }[],
  width: number,
  height: number,
): Viewport {
  if (!nodes.length || width <= 0 || height <= 0)
    return { x: 0, y: 0, zoom: 1 };
  const left = Math.min(...nodes.map((n) => n.position.x)) - NODE_WIDTH / 2;
  const right = Math.max(...nodes.map((n) => n.position.x)) + NODE_WIDTH / 2;
  const top = Math.min(...nodes.map((n) => n.position.y)) - NODE_HEIGHT / 2;
  const bottom = Math.max(...nodes.map((n) => n.position.y)) + NODE_HEIGHT / 2;
  const zoom = Math.max(
    0.1,
    Math.min(1, (width - 80) / (right - left), (height - 80) / (bottom - top)),
  );
  return {
    x: width / 2 - ((left + right) / 2) * zoom,
    y: height / 2 - ((top + bottom) / 2) * zoom,
    zoom,
  };
}

export function movePosition(
  start: Point,
  dx: number,
  dy: number,
  zoom: number,
): Point {
  const bounded = (value: number) =>
    Math.max(-100000, Math.min(100000, Math.round(value / 10) * 10));
  return { x: bounded(start.x + dx / zoom), y: bounded(start.y + dy / zoom) };
}
