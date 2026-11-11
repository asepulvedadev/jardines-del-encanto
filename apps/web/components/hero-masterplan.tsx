"use client";

import { useEffect, useRef, useState } from "react";
import type { MasterplanScene } from "../lib/hero-scene";

export default function HeroMasterplan() {
  const host = useRef<HTMLDivElement>(null);
  const scene = useRef<MasterplanScene | null>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const [selected, setSelected] = useState("");
  const [blocks, setBlocks] = useState<{ id: string; label: string }[]>([]);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    void import("../lib/hero-scene")
      .then(({ createMasterplanScene }) => {
        if (cancelled) return;
        timer = setTimeout(() => {
          if (cancelled || !host.current) return;
          try {
            const controller = createMasterplanScene(
              host.current,
              setSelected,
              () => setFailed(true),
            );
            scene.current = controller;
            setBlocks(controller.blocks);
            setReady(true);
          } catch {
            scene.current?.dispose();
            scene.current = null;
            setFailed(true);
          }
        }, 30);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
      clearTimeout(timer);
      scene.current?.dispose();
      scene.current = null;
    };
  }, []);

  function selectBlock(id: string) {
    setSelected(id);
    scene.current?.select(id);
  }

  return (
    <div className="hero-masterplan" data-3d-ready={ready && !failed}>
      <div ref={host} className="hero-plan-canvas" hidden={failed} />
      {!ready && !failed && (
        <p className="hero-world-loading" role="status">
          Dando dimensión al plano…
        </p>
      )}
      {failed && (
        <div className="hero-plan-fallback" role="status">
          {/* The source image remains available when WebGL is unsupported or lost. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/media/masterplan.webp"
            width={1500}
            height={1062}
            alt="Plano general de Jardines del Encanto"
          />
          <p>
            No pudimos abrir el 3D en este dispositivo.{" "}
            <a href="#plano">Explorar el plano 2D ↗</a>
          </p>
        </div>
      )}
      {ready && !failed && (
        <>
          <div className="hero-plan-selection">
            <label htmlFor="hero-block" className="sr-only">
              Acércate a una manzana
            </label>
            <select
              id="hero-block"
              value={selected}
              onChange={(event) => selectBlock(event.target.value)}
            >
              <option value="">Vista general</option>
              {blocks.map((block) => (
                <option value={block.id} key={block.id}>
                  {block.label}
                </option>
              ))}
            </select>
          </div>
          <div
            className="hero-plan-controls"
            role="group"
            aria-label="Controles de la maqueta"
          >
            <button
              type="button"
              aria-label="Acercar maqueta"
              onClick={() => scene.current?.zoom(0.8)}
            >
              +
            </button>
            <button
              type="button"
              aria-label="Alejar maqueta"
              onClick={() => scene.current?.zoom(1.25)}
            >
              −
            </button>
            <button
              type="button"
              aria-label="Restablecer vista general"
              onClick={() => selectBlock("")}
            >
              ↺
            </button>
          </div>
        </>
      )}
      <p className="sr-only" role="status">
        {selected
          ? `Manzana ${selected} seleccionada.`
          : "Vista general del plano."}
      </p>
    </div>
  );
}
