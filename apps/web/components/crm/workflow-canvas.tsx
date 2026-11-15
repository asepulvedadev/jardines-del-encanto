"use client";

import { useEffect, useRef, useState } from "react";
import { Icon } from "./icon";
import { kindIcons, nodeSummary } from "./workflow-node-presentation";
import {
  outgoing,
  type WorkflowDocument,
  type WorkflowNode,
} from "./workflow-types";
import {
  fitViewport,
  movePosition,
  zoomAt,
  NODE_HEIGHT,
  NODE_WIDTH,
  type Viewport,
} from "./workflow-viewport";

export function WorkflowCanvas({
  document,
  selected,
  onSelect,
  onMove,
  disabled = false,
}: {
  document: WorkflowDocument;
  selected: string;
  onSelect: (id: string) => void;
  onMove?: (id: string, position: { x: number; y: number }) => void;
  disabled?: boolean;
}) {
  const host = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<Viewport>({ x: 0, y: 0, zoom: 1 });
  const [preview, setPreview] = useState<{
    id: string;
    position: { x: number; y: number };
  } | null>(null);
  const [help, setHelp] = useState(false);
  const gesture = useRef<{
    pointer: number;
    x: number;
    y: number;
    view: Viewport;
    node?: WorkflowNode;
    moved: boolean;
  } | null>(null);
  const suppressClick = useRef(false);
  const latest = useRef({ document, disabled });
  latest.current = { document, disabled };
  const size = useRef({ width: 0, height: 0 });
  function fit() {
    const el = host.current;
    if (el)
      setView(fitViewport(document.nodes, el.clientWidth, el.clientHeight));
  }
  function zoomTo(zoom: number) {
    const el = host.current;
    if (el)
      setView((v) =>
        zoomAt(v, zoom, { x: el.clientWidth / 2, y: el.clientHeight / 2 }),
      );
  }
  useEffect(() => {
    const el = host.current;
    if (!el) return;
    size.current = { width: el.clientWidth, height: el.clientHeight };
    setView(
      fitViewport(
        latest.current.document.nodes,
        el.clientWidth,
        el.clientHeight,
      ),
    );
    const observer = new ResizeObserver(() => {
      const { width, height } = size.current;
      const w = el.clientWidth,
        h = el.clientHeight;
      size.current = { width: w, height: h };
      setView((v) =>
        width
          ? { ...v, x: v.x + (w - width) / 2, y: v.y + (h - height) / 2 }
          : fitViewport(latest.current.document.nodes, w, h),
      );
    });
    observer.observe(el);
    // A native non-passive listener prevents page scrolling only over the canvas.
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      const rect = el.getBoundingClientRect();
      if (event.ctrlKey || event.metaKey) {
        setView((v) =>
          zoomAt(v, v.zoom * Math.exp(-event.deltaY * 0.008), {
            x: event.clientX - rect.left,
            y: event.clientY - rect.top,
          }),
        );
      } else {
        const unit =
          event.deltaMode === 1
            ? 16
            : event.deltaMode === 2
              ? el.clientHeight
              : 1;
        setView((v) => ({
          ...v,
          x: v.x - event.deltaX * unit,
          y: v.y - event.deltaY * unit,
        }));
      }
    };
    el.addEventListener("wheel", wheel, { passive: false });
    return () => {
      observer.disconnect();
      el.removeEventListener("wheel", wheel);
    };
  }, []);
  useEffect(() => {
    const node = document.nodes.find((n) => n.id === selected);
    const el = host.current;
    if (!node || !el) return;
    setView((v) => {
      const x = v.x + node.position.x * v.zoom,
        y = v.y + node.position.y * v.zoom;
      if (
        x < NODE_WIDTH / 2 ||
        x > el.clientWidth - NODE_WIDTH / 2 ||
        y < 70 ||
        y > el.clientHeight - 70
      )
        return {
          ...v,
          x: el.clientWidth / 2 - node.position.x * v.zoom,
          y: el.clientHeight / 2 - node.position.y * v.zoom,
        };
      return v;
    });
  }, [selected, document.nodes.length]);
  const nodes = document.nodes.map((n) =>
    preview?.id === n.id ? { ...n, position: preview.position } : n,
  );
  const positions = new Map(nodes.map((n) => [n.id, n.position]));
  const left = Math.min(0, ...nodes.map((n) => n.position.x - NODE_WIDTH));
  const top = Math.min(0, ...nodes.map((n) => n.position.y - NODE_HEIGHT));
  const right = Math.max(660, ...nodes.map((n) => n.position.x + NODE_WIDTH));
  const bottom = Math.max(480, ...nodes.map((n) => n.position.y + NODE_HEIGHT));
  return (
    <div className="workflow-canvas-shell">
      <div
        ref={host}
        className="workflow-map-scroll"
        role="region"
        aria-label="Mapa visual de pasos; también disponible en la lista inferior"
        tabIndex={0}
        style={{
          backgroundPosition: `${view.x}px ${view.y}px`,
          backgroundSize: `${24 * view.zoom}px ${24 * view.zoom}px`,
        }}
        onKeyDown={(event) => {
          if (event.target !== event.currentTarget) return;
          const delta = {
            ArrowLeft: [60, 0],
            ArrowRight: [-60, 0],
            ArrowUp: [0, 60],
            ArrowDown: [0, -60],
          }[event.key];
          if (delta) {
            event.preventDefault();
            setView((v) => ({ ...v, x: v.x + delta[0], y: v.y + delta[1] }));
          } else if (["+", "=", "-", "0", "1"].includes(event.key)) {
            event.preventDefault();
            if (event.key === "1") fit();
            else
              zoomTo(
                event.key === "0"
                  ? 1
                  : view.zoom * (event.key === "-" ? 0.8 : 1.25),
              );
          }
        }}
        onPointerDown={(event) => {
          if (event.button !== 0 && event.button !== 1) return;
          if (
            event.target !== event.currentTarget &&
            (event.target as HTMLElement).closest("button")
          )
            return;
          event.preventDefault();
          host.current?.focus({ preventScroll: true });
          event.currentTarget.setPointerCapture(event.pointerId);
          gesture.current = {
            pointer: event.pointerId,
            x: event.clientX,
            y: event.clientY,
            view,
            moved: false,
          };
        }}
        onPointerMove={(event) => {
          const g = gesture.current;
          if (!g || g.pointer !== event.pointerId) return;
          const dx = event.clientX - g.x,
            dy = event.clientY - g.y;
          if (Math.abs(dx) + Math.abs(dy) < 4 && !g.moved) return;
          g.moved = true;
          if (g.node) {
            if (!latest.current.disabled)
              setPreview({
                id: g.node.id,
                position: movePosition(g.node.position, dx, dy, g.view.zoom),
              });
          } else setView({ ...g.view, x: g.view.x + dx, y: g.view.y + dy });
        }}
        onPointerUp={(event) => {
          const g = gesture.current;
          if (!g || g.pointer !== event.pointerId) return;
          suppressClick.current = g.moved;
          if (g.node && g.moved && !disabled)
            onMove?.(
              g.node.id,
              movePosition(
                g.node.position,
                event.clientX - g.x,
                event.clientY - g.y,
                g.view.zoom,
              ),
            );
          gesture.current = null;
          setPreview(null);
        }}
        onPointerCancel={() => {
          gesture.current = null;
          setPreview(null);
        }}
      >
        <div
          className="workflow-map"
          style={{
            transform: `translate(${view.x}px, ${view.y}px) scale(${view.zoom})`,
          }}
        >
          <svg
            width={right - left}
            height={bottom - top}
            viewBox={`${left} ${top} ${right - left} ${bottom - top}`}
            style={{ left, top }}
            aria-hidden="true"
            className="workflow-wires"
          >
            <defs>
              <marker
                id="workflow-arrow"
                markerWidth="8"
                markerHeight="8"
                refX="7"
                refY="4"
                orient="auto"
              >
                <path d="M0 0L8 4L0 8" fill="none" stroke="currentColor" />
              </marker>
            </defs>
            {nodes.flatMap((node) =>
              outgoing(node).map((target, index) => {
                const end = positions.get(target);
                if (!end) return null;
                const branch = node.kind === "condition";
                const x =
                  node.position.x + (branch ? (index === 0 ? -55 : 55) : 0);
                const y = node.position.y + NODE_HEIGHT / 2,
                  targetY = end.y - NODE_HEIGHT / 2;
                return (
                  <g key={`${node.id}-${target}-${index}`}>
                    <path
                      d={`M${x},${y} C${x},${y + 55} ${end.x},${targetY - 55} ${end.x},${targetY}`}
                      fill="none"
                      stroke={branch && index === 1 ? "#855708" : "#507010"}
                      strokeWidth="1.8"
                      markerEnd="url(#workflow-arrow)"
                    />
                    {branch ? (
                      <text
                        x={x + 8}
                        y={y + 23}
                        fill={index === 0 ? "#507010" : "#855708"}
                      >
                        {index === 0 ? "Sí" : "No"}
                      </text>
                    ) : null}
                  </g>
                );
              }),
            )}
          </svg>
          {nodes.map((node, index) => (
            <button
              key={node.id}
              className={`workflow-node ${selected === node.id ? "is-selected" : ""} is-${node.kind}`}
              style={{ left: node.position.x, top: node.position.y }}
              aria-pressed={selected === node.id}
              aria-label={`Paso ${index + 1}: ${node.label}. ${nodeSummary(node)}`}
              onPointerDown={(event) => {
                if (disabled || event.button !== 0) return;
                event.stopPropagation();
                suppressClick.current = false;
                event.currentTarget.setPointerCapture(event.pointerId);
                gesture.current = {
                  pointer: event.pointerId,
                  x: event.clientX,
                  y: event.clientY,
                  view,
                  node,
                  moved: false,
                };
              }}
              onClick={() => {
                if (!suppressClick.current) onSelect(node.id);
                suppressClick.current = false;
              }}
              onKeyDown={(event) => {
                const delta = {
                  ArrowLeft: [-10, 0],
                  ArrowRight: [10, 0],
                  ArrowUp: [0, -10],
                  ArrowDown: [0, 10],
                }[event.key];
                if (event.altKey && delta && !disabled && onMove) {
                  event.preventDefault();
                  event.stopPropagation();
                  onMove(
                    node.id,
                    movePosition(
                      node.position,
                      delta[0] * (event.shiftKey ? 5 : 1),
                      delta[1] * (event.shiftKey ? 5 : 1),
                      1,
                    ),
                  );
                }
              }}
            >
              <span className="workflow-node-port is-input" />
              <span className="workflow-node-icon">
                <Icon name={kindIcons[node.kind]} size={20} />
              </span>
              <span className="workflow-node-body">
                <strong>{node.label}</strong>
                <span>{nodeSummary(node)}</span>
              </span>
              {node.id === document.entry_id ? (
                <span className="workflow-entry-badge">Inicio</span>
              ) : (
                <span className="workflow-node-number">{index + 1}</span>
              )}
              {node.kind !== "end" ? (
                <span className="workflow-node-port is-output" />
              ) : null}
            </button>
          ))}
        </div>
      </div>
      <div
        className="workflow-zoom-controls"
        role="group"
        aria-label="Controles del lienzo"
      >
        <button
          aria-label="Alejar lienzo"
          disabled={view.zoom <= 0.1}
          onClick={() => zoomTo(view.zoom / 1.25)}
        >
          −
        </button>
        <button aria-label="Restablecer zoom al 100%" onClick={() => zoomTo(1)}>
          {Math.round(view.zoom * 100)}%
        </button>
        <button
          aria-label="Acercar lienzo"
          disabled={view.zoom >= 2}
          onClick={() => zoomTo(view.zoom * 1.25)}
        >
          +
        </button>
        <span />
        <button aria-label="Encajar todos los pasos" onClick={fit}>
          <Icon name="connections" size={18} />
        </button>
        <button
          aria-label="Ayuda del lienzo"
          aria-expanded={help}
          onClick={() => setHelp(!help)}
        >
          ?
        </button>
      </div>
      {help ? (
        <div className="workflow-canvas-help" role="note">
          Arrastra el fondo para moverte y los bloques para ordenarlos. Rueda o
          dos dedos: desplazar. Ctrl/⌘ + rueda: zoom.
          <br />
          Teclado en el lienzo: + / −, 0 al 100%, 1 encajar, flechas para
          desplazarte. En un bloque: Alt + flechas para moverlo.
        </div>
      ) : null}
    </div>
  );
}
