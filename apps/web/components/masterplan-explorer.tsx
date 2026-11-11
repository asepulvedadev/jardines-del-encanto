"use client";

import {
  useCallback,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
} from "react";
import sourceData from "../lib/masterplan-data.json";
import type { MasterplanData, MasterplanLot } from "../lib/masterplan-types";
import { whatsappLink } from "../lib/project";
import "../app/masterplan.css";

const plan = sourceData as MasterplanData;
const lotById = new Map(plan.lots.map((lot) => [lot.id, lot]));
const baseView = plan.viewBox;
const lotsByBlock = new Map(
  plan.blocks.map((block) => [
    block.id,
    plan.lots.filter((lot) => lot.blockId === block.id),
  ]),
);

function bounded(view: number[]): number[] {
  const width = Math.min(view[2], baseView[2]);
  const height = Math.min(view[3], baseView[3]);
  return [
    Math.max(baseView[0], Math.min(baseView[0] + baseView[2] - width, view[0])),
    Math.max(
      baseView[1],
      Math.min(baseView[1] + baseView[3] - height, view[1]),
    ),
    width,
    height,
  ];
}
const number = new Intl.NumberFormat("es-CO", { maximumFractionDigits: 2 });

function fitted(bounds: number[]): number[] {
  const width = Math.max(bounds[2] - bounds[0], 45);
  const height = Math.max(bounds[3] - bounds[1], 45);
  return [
    bounds[0] - width * 0.15,
    bounds[1] - height * 0.15,
    width * 1.3,
    height * 1.3,
  ];
}

export function MasterplanExplorer() {
  const [blockId, setBlockId] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [query, setQuery] = useState("");
  const [view, setView] = useState<number[]>(baseView);
  const svg = useRef<SVGSVGElement>(null);
  const gesture = useRef<{
    x: number;
    y: number;
    view: number[];
    moved: boolean;
    target: string | null;
  } | null>(null);
  const selected = lotById.get(selectedId);
  const visibleLots = useMemo(
    () =>
      plan.lots.filter(
        (lot) =>
          (!blockId || lot.blockId === blockId) &&
          (!query ||
            lot.sourceLabel.toLowerCase().includes(query.toLowerCase())),
      ),
    [blockId, query],
  );

  function selectBlock(id: string) {
    setBlockId(id);
    setSelectedId("");
    setQuery("");
    const block = plan.blocks.find((item) => item.id === id);
    setView(block ? bounded(fitted(block.bounds)) : baseView);
  }
  function openBlock(id: string) {
    selectBlock(id);
    window.requestAnimationFrame(() =>
      svg.current?.focus({ preventScroll: true }),
    );
  }
  const selectLot = useCallback((lot: MasterplanLot) => {
    setBlockId(lot.blockId);
    setSelectedId(lot.id);
    setView(bounded(fitted(lot.bounds)));
  }, []);
  function activate(id: string) {
    const lot = lotById.get(id);
    if (!lot) return;
    if (!blockId) selectBlock(lot.blockId);
    else selectLot(lot);
  }
  function zoom(factor: number) {
    setView((previous) => {
      const width = Math.min(baseView[2], Math.max(35, previous[2] / factor));
      const scale = width / previous[2];
      return bounded([
        previous[0] + (previous[2] * (1 - scale)) / 2,
        previous[1] + (previous[3] * (1 - scale)) / 2,
        width,
        previous[3] * scale,
      ]);
    });
  }
  function point(event: PointerEvent<SVGSVGElement>) {
    const matrix = svg.current?.getScreenCTM();
    return matrix
      ? new DOMPoint(event.clientX, event.clientY).matrixTransform(
          matrix.inverse(),
        )
      : null;
  }
  function pointerDown(event: PointerEvent<SVGSVGElement>) {
    if (event.button !== 0) return;
    const p = point(event);
    if (!p) return;
    gesture.current = {
      x: p.x,
      y: p.y,
      view: [...view],
      moved: false,
      target:
        (event.target as Element)
          .closest("[data-source-lot]")
          ?.getAttribute("data-source-lot") ?? null,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function pointerMove(event: PointerEvent<SVGSVGElement>) {
    const current = gesture.current;
    if (!current) return;
    const p = point(event);
    if (!p) return;
    // Convert against the gesture's original view to avoid cumulative pan drift.
    const matrix = svg.current?.getScreenCTM();
    if (!matrix) return;
    const dx = p.x - current.x;
    const dy = p.y - current.y;
    if (Math.hypot(dx * matrix.a, dy * matrix.d) < 4 && !current.moved) return;
    current.moved = true;
    setView((previous) =>
      bounded([previous[0] - dx, previous[1] - dy, previous[2], previous[3]]),
    );
  }
  function pointerUp(event: PointerEvent<SVGSVGElement>) {
    const current = gesture.current;
    gesture.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId))
      event.currentTarget.releasePointerCapture(event.pointerId);
    if (event.type === "pointerup" && current?.target && !current.moved)
      activate(current.target);
  }
  function keyboard(event: KeyboardEvent<SVGSVGElement>) {
    const directions: Record<string, number[]> = {
      ArrowLeft: [-1, 0],
      ArrowRight: [1, 0],
      ArrowUp: [0, -1],
      ArrowDown: [0, 1],
    };
    if (directions[event.key]) {
      event.preventDefault();
      const [x, y] = directions[event.key];
      setView((previous) =>
        bounded([
          previous[0] + x * previous[2] * 0.1,
          previous[1] + y * previous[3] * 0.1,
          previous[2],
          previous[3],
        ]),
      );
    } else if (event.key === "+" || event.key === "=") {
      event.preventDefault();
      zoom(1.5);
    } else if (event.key === "-") {
      event.preventDefault();
      zoom(1 / 1.5);
    } else if (event.key === "Home" || event.key === "Escape") {
      event.preventDefault();
      selectBlock("");
    }
  }
  const geometry = useMemo(
    () =>
      plan.blocks.map((block) => (
        <g
          key={block.id}
          data-source-block={block.id}
          role="group"
          aria-label={block.label}
          opacity={!blockId || blockId === block.id ? 1 : 0.18}
        >
          {(lotsByBlock.get(block.id) ?? []).map((lot) =>
            lot.path ? (
              <path
                key={lot.id}
                d={lot.path}
                data-source-lot={lot.id}
                className={`masterplan-lot ${lot.id === selectedId ? "is-selected" : ""}`}
                role="button"
                tabIndex={blockId === lot.blockId ? 0 : -1}
                aria-label={`${lot.sourceLabel}${lot.anomalies.includes("duplicate-source-label") ? ", rótulo duplicado en la fuente" : ""}${lot.areaM2 !== null ? `, ${number.format(lot.areaM2)} metros cuadrados` : ""}`}
                aria-pressed={selectedId === lot.id}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    selectLot(lot);
                  }
                }}
              >
                <title>{`${lot.sourceLabel} · ${lot.areaM2 !== null ? `${number.format(lot.areaM2)} m²` : "Área por confirmar"}`}</title>
              </path>
            ) : (
              <circle
                key={lot.id}
                data-source-lot={lot.id}
                cx={lot.center[0]}
                cy={lot.center[1]}
                r={4}
                className="masterplan-unresolved"
                role="button"
                tabIndex={blockId === lot.blockId ? 0 : -1}
                aria-label={`${lot.sourceLabel}, contorno por validar`}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    selectLot(lot);
                  }
                }}
              >
                <title>{`${lot.sourceLabel}: ubicación del rótulo, no delimitación del lote`}</title>
              </circle>
            ),
          )}
        </g>
      )),
    [blockId, selectedId, selectLot],
  );
  const measurements = selected
    ? [
        ...new Set(
          selected.measurements.map((measurement) => measurement.value),
        ),
      ]
    : [];

  return (
    <div className="masterplan" data-plan-explorer>
      <div className="masterplan-toolbar">
        <label>
          1. Elige una manzana
          <select
            value={blockId}
            onChange={(event) => selectBlock(event.target.value)}
          >
            <option value="">Ver todo el proyecto</option>
            {plan.blocks.map((block) => (
              <option key={block.id} value={block.id}>
                {block.label} · {block.count} rótulos
              </option>
            ))}
          </select>
        </label>
        <label>
          Buscar rótulo del plano
          <input
            type="search"
            placeholder="Ej.: LT 1-1"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <label>
          2. Consulta un lote
          <select
            value={selectedId}
            onChange={(event) => {
              const lot = lotById.get(event.target.value);
              if (lot) selectLot(lot);
            }}
          >
            <option value="">
              Selecciona un rótulo ({visibleLots.length})
            </option>
            {visibleLots.map((lot) => (
              <option key={lot.id} value={lot.id}>
                {lot.sourceLabel}
                {lot.anomalies.includes("duplicate-source-label")
                  ? ` · referencia ${lot.id.slice(-4)}`
                  : ""}
                {!lot.path ? " · contorno por validar" : ""}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="masterplan-workspace">
        <div className="masterplan-canvas">
          <div className="masterplan-map-hint">
            {blockId
              ? `Manzana ${blockId} · selecciona un lote`
              : "Selecciona una manzana para explorar sus lotes"}
          </div>
          <svg
            data-masterplan
            ref={svg}
            viewBox={view.join(" ")}
            role="group"
            aria-label="Plano vectorial interactivo de Jardines del Encanto"
            aria-describedby="masterplan-instructions"
            tabIndex={0}
            onKeyDown={keyboard}
            onPointerDown={pointerDown}
            onPointerMove={pointerMove}
            onPointerUp={pointerUp}
            onPointerCancel={pointerUp}
          >
            <title>Manzanas y lotes según el plano suministrado</title>
            <image
              href="/media/masterplan-context.svg"
              x="0"
              y="0"
              width="2835"
              height="4008"
              aria-hidden="true"
            />
            {geometry}
            {!blockId &&
              plan.blocks.map((block) => {
                const size = Math.max(view[2] / 58, view[3] / 42) * 0.85;
                const x = (block.bounds[0] + block.bounds[2]) / 2;
                const y = (block.bounds[1] + block.bounds[3]) / 2;
                return (
                  <g
                    key={block.id}
                    className="masterplan-block-target"
                    data-block-label={block.id}
                    role="button"
                    tabIndex={0}
                    aria-label={`Explorar manzana ${block.id}`}
                    onPointerDown={(event) => event.stopPropagation()}
                    onClick={() => openBlock(block.id)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        event.stopPropagation();
                        openBlock(block.id);
                      }
                    }}
                  >
                    <title>{`Explorar manzana ${block.id}`}</title>
                    <circle cx={x} cy={y} r={size * 0.82} />
                    <text x={x} y={y} dy=".35em" style={{ fontSize: size }}>
                      {block.id}
                    </text>
                  </g>
                );
              })}
            {selected?.path && (
              <text
                className="masterplan-selected-label"
                x={selected.center[0]}
                y={selected.center[1]}
                fontSize={Math.max(2, view[2] / 34)}
                aria-hidden="true"
              >
                {selected.sourceLabel}
              </text>
            )}
          </svg>
          <div className="masterplan-controls" aria-label="Controles del plano">
            <button
              type="button"
              onClick={() => zoom(1.5)}
              aria-label="Acercar plano"
            >
              +
            </button>
            <button
              type="button"
              onClick={() => zoom(1 / 1.5)}
              aria-label="Alejar plano"
            >
              −
            </button>
            <button type="button" onClick={() => selectBlock("")}>
              Ver todo
            </button>
            {blockId && (
              <button type="button" onClick={() => selectBlock(blockId)}>
                Ver manzana
              </button>
            )}
          </div>
        </div>
        <aside className="masterplan-detail" aria-label="Ficha del lote">
          <p className="masterplan-step">Tu próximo espacio</p>
          {selected ? (
            <>
              <h3>{selected.sourceLabel}</h3>
              <p>Manzana {selected.blockId}</p>
              <dl>
                <div>
                  <dt>Área según el plano</dt>
                  <dd>
                    {selected.areaM2 !== null ? (
                      `${number.format(selected.areaM2)} m²`
                    ) : selected.areaLabel ? (
                      <>
                        {selected.areaLabel}
                        <small className="masterplan-area-note">
                          Unidad no indicada en el plano. Confirma el dato con
                          un asesor.
                        </small>
                      </>
                    ) : (
                      "Por confirmar"
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Medidas rotuladas en sus bordes</dt>
                  <dd>
                    {measurements.length
                      ? measurements
                          .map((value) => `${number.format(Number(value))} m`)
                          .join(" · ")
                      : "Pendientes de asociación verificable"}
                  </dd>
                </div>
                <div>
                  <dt>Disponibilidad y precio</dt>
                  <dd>Confirma con un asesor</dd>
                </div>
              </dl>
              {selected.anomalies.length > 0 && (
                <p className="masterplan-notice">
                  {selected.anomalies.includes("duplicate-source-label") &&
                    "Este rótulo aparece más de una vez en la fuente. "}
                  {selected.anomalies.includes("malformed-source-label") &&
                    "El identificador original tiene un formato irregular; no lo hemos corregido. "}
                  {!selected.path &&
                    "El contorno requiere validación; el punto solo ubica el rótulo, no representa sus límites. "}
                  {selected.anomalies.includes("multiple-source-area-labels") &&
                    "Hay más de un área rotulada dentro de este contorno; confirma el dato con un asesor. "}
                  {selected.anomalies.includes("spatial-block-association") &&
                    "La asociación a la manzana es espacial, no una corrección del rótulo. "}
                  Referencia interna: {selected.id}.
                </p>
              )}
              <a
                className="masterplan-cta"
                href={whatsappLink(
                  `Hola, quiero mi cupo para conocer el ${selected.sourceLabel} de Jardines del Encanto, manzana ${selected.blockId}${selected.areaM2 !== null ? `, área indicada ${selected.areaM2} m²` : ""}. Referencia del plano: ${selected.id}. ¿Me confirman medidas, precio y disponibilidad?`,
                )}
                target="_blank"
                rel="noopener noreferrer"
              >
                Quiero conocer este lote <span aria-hidden="true">↗</span>
              </a>
            </>
          ) : (
            <>
              <h3>Elige dónde comienza tu historia.</h3>
              <p>
                Acércate a una manzana y selecciona un lote. También puedes usar
                los selectores sin navegar el dibujo.
              </p>
              <div className="masterplan-stat">
                <strong>{plan.blocks.length}</strong>
                <span>manzanas identificadas en la fuente</span>
              </div>
              <p className="masterplan-subtle">
                El plano muestra distribución y medidas, no disponibilidad en
                tiempo real.
              </p>
            </>
          )}
        </aside>
      </div>
      <p id="masterplan-instructions" className="masterplan-instructions">
        Arrastra para desplazarte. Usa + y − para acercar o alejar; con teclado,
        usa las flechas y la tecla Inicio para volver al proyecto. Puedes
        consultar cualquier rótulo desde los selectores.
      </p>
      <details className="masterplan-provenance">
        <summary>Cómo leer este plano y sus referencias</summary>
        <p>
          Geometría extraída de los vectores del plano suministrado. Las áreas y
          medidas son rótulos impresos, no una nueva medición ni una
          certificación catastral. No se asignan estados de venta ni se corrigen
          identificadores de la fuente.
        </p>
        <p>
          {plan.metadata.sourceLabelOccurrences} apariciones de rótulos ·{" "}
          {plan.metadata.resolvedGeometry} contornos individualizados ·{" "}
          {plan.metadata.unresolvedGeometry} contornos pendientes de validación.
          Los rótulos duplicados conservan referencias internas distintas.
        </p>
        {plan.metadata.unresolvedGeometry > 0 && (
          <p>
            Sin contorno individual verificado:{" "}
            {plan.lots
              .filter((lot) => !lot.path)
              .map((lot) => lot.sourceLabel)
              .join(" · ")}
            . Se conservan en los selectores.
          </p>
        )}
      </details>
    </div>
  );
}
