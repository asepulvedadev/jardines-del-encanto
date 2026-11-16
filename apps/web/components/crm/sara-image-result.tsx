"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { SettingsRequest } from "./settings-types";
import "./sara-images.css";

type ImageReceipt = {
  kind: "image";
  id: string;
  status: "queued" | "processing" | "completed" | "unknown" | "failed";
  concept: true;
  reference_ids: string[];
  url: string | null;
  size: number | null;
};
const references: Record<string, string> = {
  "logo-white": "Logo blanco original",
  "logo-transparent": "Logo transparente original",
  "photo-aerial": "Fotografía aérea original",
  "photo-entrance": "Fotografía original de la entrada",
  "photo-gate": "Fotografía original de la portería",
};
const labels = {
  queued: "Imagen en espera",
  processing: "Creando concepto visual…",
  completed: "Concepto visual generado",
  unknown:
    "No se pudo confirmar el resultado. No se volverá a generar automáticamente.",
  failed: "No se pudo crear la imagen.",
};

function parseReceipt(value: unknown): ImageReceipt | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  if (
    row.kind !== "image" ||
    row.concept !== true ||
    row.mime_type !== "image/png" ||
    typeof row.id !== "string" ||
    !/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(row.id) ||
    typeof row.status !== "string" ||
    !Object.hasOwn(labels, row.status) ||
    !Array.isArray(row.reference_ids) ||
    row.reference_ids.length > 3 ||
    new Set(row.reference_ids).size !== row.reference_ids.length ||
    row.reference_ids.some(
      (id) => typeof id !== "string" || !Object.hasOwn(references, id),
    )
  )
    return null;
  if (
    row.status === "completed" &&
    (row.url !== `/api/crm/images/${row.id}/content` ||
      typeof row.size !== "number" ||
      !Number.isSafeInteger(row.size) ||
      row.size < 1 ||
      row.size > 8 * 1024 * 1024)
  )
    return null;
  return row as ImageReceipt;
}

/** Receipt metadata is not image evidence: preview only authenticated bounded bytes. */
export function SaraImageResult({
  result,
  request,
  active = true,
}: {
  result: unknown;
  request: SettingsRequest;
  active?: boolean;
}) {
  const initial = useMemo(() => parseReceipt(result), [result]);
  const [latest, setLatest] = useState<ImageReceipt | null>(null);
  const [preview, setPreview] = useState<{ id: string; url: string } | null>(
    null,
  );
  const [error, setError] = useState("");
  const poll = useRef({ id: "", attempts: 0 });
  const receipt = latest?.id === initial?.id ? latest : initial;
  const id = receipt?.id;
  const status = receipt?.status;

  useEffect(() => {
    setLatest(null);
    setError("");
  }, [initial?.id]);

  useEffect(() => {
    if (!active || !id || (status !== "queued" && status !== "processing"))
      return;
    if (poll.current.id !== id) poll.current = { id, attempts: 0 };
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function update() {
      if (poll.current.attempts >= 60) {
        setError(
          "La imagen sigue pendiente. Vuelve a abrir la conversación para consultar su estado; no se repetirá la generación.",
        );
        return;
      }
      poll.current.attempts += 1;
      try {
        const next = parseReceipt(await request<unknown>(`images/${id}`));
        if (cancelled) return;
        if (!next || next.id !== id) throw new Error("invalid_receipt");
        setLatest(next);
        if (next.status === "queued" || next.status === "processing")
          timer = setTimeout(update, 3000);
      } catch {
        if (!cancelled)
          setError(
            "No se pudo consultar la imagen. La generación no se repetirá automáticamente.",
          );
      }
    }
    timer = setTimeout(update, 1500);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [active, id, status, request]);

  useEffect(() => {
    if (!active || !id || status !== "completed") return;
    const abort = new AbortController();
    let objectUrl = "";
    setError("");
    async function load() {
      try {
        const response = await fetch(`/api/crm/images/${id}/content`, {
          credentials: "same-origin",
          cache: "no-store",
          redirect: "error",
          signal: abort.signal,
        });
        if (
          !response.ok ||
          response.headers.get("content-type")?.split(";")[0] !== "image/png" ||
          !response.body
        ) {
          throw new Error("invalid_image");
        }
        const reader = response.body.getReader();
        const chunks: Uint8Array<ArrayBuffer>[] = [];
        let length = 0;
        while (true) {
          const chunk = await reader.read();
          if (chunk.done) break;
          length += chunk.value.byteLength;
          if (length > 8 * 1024 * 1024) {
            await reader.cancel();
            throw new Error("image_limit");
          }
          chunks.push(new Uint8Array(chunk.value));
        }
        if (!length || abort.signal.aborted) return;
        objectUrl = URL.createObjectURL(
          new Blob(chunks, { type: "image/png" }),
        );
        setPreview({ id: id!, url: objectUrl });
      } catch {
        if (!abort.signal.aborted)
          setError(
            "No se pudo cargar la imagen privada. No se ha confirmado una vista previa.",
          );
      }
    }
    void load();
    return () => {
      abort.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [active, id, status]);

  if (!receipt) return null;
  const visible = active && preview?.id === id ? (preview?.url ?? "") : "";
  return (
    <figure className="sara-image-result" aria-label="Concepto visual de Sara">
      <p role="status">{labels[receipt.status]}</p>
      {receipt.status === "completed" && !visible && !error && (
        <p>Cargando imagen privada…</p>
      )}
      {visible && !error && (
        // Authenticated blob URLs require a native image, never a remote optimizer.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={visible}
          alt="Concepto visual generado por IA para Jardines del Encanto"
          onError={() =>
            setError("El archivo recibido no se pudo mostrar como imagen.")
          }
        />
      )}
      {error && (
        <p className="crm-error" role="alert">
          {error}
        </p>
      )}
      <figcaption>
        <strong>Concepto generado por IA.</strong> No acredita el estado real
        del proyecto ni confirma información comercial.
        <span>
          {receipt.reference_ids.length
            ? `Referencias: ${receipt.reference_ids.map((key) => references[key]).join(", ")}.`
            : "Sin fotografías ni logos de referencia."}
        </span>
      </figcaption>
    </figure>
  );
}
