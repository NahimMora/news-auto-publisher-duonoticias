"use client";

import React, { useEffect, useRef, useState } from "react";
import { api, type RenderJobDTO } from "../../lib/client/api";
import { isStillTemplate } from "../../src/templates/meta";
import type { Piece } from "../../src/schema/piece";

/**
 * Exportacion real (Node + Remotion en este equipo): MP4 para video, PNG/JPG
 * para posts. Progreso real del render y descarga del archivo.
 */
export const ExportPanel: React.FC<{ projectId: string; piece: Piece; beforeExport: () => Promise<void> }> = ({ projectId, piece, beforeExport }) => {
  const [job, setJob] = useState<RenderJobDTO | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const still = isStillTemplate(piece.presentation.template);

  useEffect(() => () => {
    if (timer.current) clearInterval(timer.current);
  }, []);

  const start = async (kind: "mp4" | "png" | "jpeg") => {
    setError(null);
    try {
      await beforeExport();
      const j = await api.startRender(projectId, kind);
      setJob(j);
      if (timer.current) clearInterval(timer.current);
      timer.current = setInterval(async () => {
        try {
          const s = await api.renderStatus(j.id);
          setJob(s);
          if (s.status === "done" || s.status === "error") {
            if (timer.current) clearInterval(timer.current);
            if (s.status === "error") setError(s.error ?? "Error de render");
          }
        } catch (e) {
          if (timer.current) clearInterval(timer.current);
          setError(e instanceof Error ? e.message : String(e));
        }
      }, 700);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const running = job && (job.status === "queued" || job.status === "bundling" || job.status === "rendering");
  const label =
    job?.status === "queued" ? "En cola" : job?.status === "bundling" ? "Preparando motor" : job?.status === "rendering" ? `Renderizando ${Math.round(job.progress * 100)} %` : "";

  return (
    <div className="flex items-center gap-3">
      {running ? (
        <div className="flex items-center gap-3">
          <div className="h-1.5 w-40 overflow-hidden bg-line">
            <div className="h-full bg-amber transition-[width]" style={{ width: `${Math.max(4, (job?.progress ?? 0) * 100)}%` }} />
          </div>
          <span className="font-mono text-[11px] text-soft">{label}</span>
        </div>
      ) : job?.status === "done" && job.file ? (
        <a href={`/api/media/renders/${job.file}?download=1`} className="font-mono text-[11.5px] text-amber underline underline-offset-4">
          Descargar {job.file.split(".").pop()?.toUpperCase()} · {((job.ms ?? 0) / 1000).toFixed(1)} s
        </a>
      ) : null}
      {error ? <span className="max-w-[320px] truncate text-[12px] text-signal" title={error}>{error}</span> : null}
      {still ? (
        <>
          <button disabled={!!running} onClick={() => start("png")} className="border border-line-strong px-3 py-1.5 text-[13px] hover:border-amber disabled:opacity-40">
            PNG
          </button>
          <button disabled={!!running} onClick={() => start("jpeg")} className="bg-amber px-4 py-1.5 text-[13px] font-[700] text-ink hover:opacity-90 disabled:opacity-40">
            Exportar JPG
          </button>
        </>
      ) : (
        <button disabled={!!running} onClick={() => start("mp4")} className="bg-amber px-4 py-1.5 text-[13px] font-[700] text-ink hover:opacity-90 disabled:opacity-40">
          Exportar MP4
        </button>
      )}
    </div>
  );
};
