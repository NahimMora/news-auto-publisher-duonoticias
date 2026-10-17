"use client";

import Link from "next/link";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../lib/client/api";
import { pieceSchema, type Piece, type Project } from "../../src/schema/piece";
import { ExportPanel } from "./ExportPanel";
import { ContentForm, DesignForm, MotionForm } from "./Forms";
import { PreviewStage } from "./PreviewStage";

type Tab = "content" | "design" | "motion";
type SaveState = "saved" | "dirty" | "saving" | "error";

/**
 * Editor de piezas: formulario a la izquierda (contenido / diseno / movimiento),
 * previsualizacion protagonista y exportacion. Guardado automatico.
 */
export const Editor: React.FC<{ projectId: string }> = ({ projectId }) => {
  const [project, setProject] = useState<Project | null>(null);
  const [piece, setPiece] = useState<Piece | null>(null);
  const [preview, setPreview] = useState<Piece | null>(null);
  const [issues, setIssues] = useState<string[]>([]);
  const [tab, setTab] = useState<Tab>("content");
  const [save, setSave] = useState<SaveState>("saved");
  const [loadError, setLoadError] = useState<string | null>(null);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latest = useRef<{ piece: Piece | null; name: string }>({ piece: null, name: "" });

  useEffect(() => {
    api
      .getProject(projectId)
      .then((p) => {
        setProject(p);
        setPiece(p.piece);
        setPreview(p.piece);
        latest.current = { piece: p.piece, name: p.name };
      })
      .catch((e) => setLoadError(e instanceof Error ? e.message : String(e)));
  }, [projectId]);

  const persist = useCallback(async () => {
    if (saveTimer.current) clearTimeout(saveTimer.current);
    const { piece: current, name } = latest.current;
    if (!current) return;
    const parsed = pieceSchema.safeParse(current);
    if (!parsed.success) return;
    setSave("saving");
    try {
      await api.saveProject(projectId, { piece: parsed.data, name });
      setSave("saved");
    } catch {
      setSave("error");
    }
  }, [projectId]);

  const schedule = useCallback(() => {
    setSave("dirty");
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(persist, 900);
  }, [persist]);

  const update = useCallback(
    (fn: (draft: Piece) => void) => {
      const prev = latest.current.piece;
      if (!prev) return;
      const draft = structuredClone(prev);
      fn(draft);
      latest.current.piece = draft;
      setPiece(draft);
      const parsed = pieceSchema.safeParse(draft);
      if (parsed.success) {
        setPreview(parsed.data);
        setIssues([]);
      } else {
        setIssues(parsed.error.issues.slice(0, 4).map((i) => `${i.path.join(".")}: ${i.message}`));
      }
      schedule();
    },
    [schedule],
  );

  if (loadError) {
    return (
      <div className="p-10">
        <div className="text-signal">{loadError}</div>
        <Link href="/" className="mt-4 inline-block text-amber underline">
          Volver
        </Link>
      </div>
    );
  }
  if (!project || !piece || !preview) return <div className="p-10 font-mono text-sm text-mute">Cargando proyecto…</div>;

  return (
    <div className="grid h-screen grid-rows-[56px_1fr]">
      <header className="flex items-center justify-between border-b border-line bg-panel px-5">
        <div className="flex min-w-0 items-center gap-4">
          <Link href="/" className="font-mono text-[11px] uppercase tracking-wider text-mute hover:text-white">
            ← Proyectos
          </Link>
          <input
            className="w-[420px] min-w-0 border-b border-transparent bg-transparent text-[15px] font-[680] outline-none focus:border-amber"
            value={latest.current.name}
            onChange={(e) => {
              latest.current.name = e.target.value;
              setProject({ ...project, name: e.target.value });
              schedule();
            }}
          />
          <span className={`font-mono text-[10.5px] uppercase tracking-wider ${save === "error" ? "text-signal" : save === "saved" ? "text-mute" : "text-amber"}`}>
            {save === "saved" ? "Guardado" : save === "saving" ? "Guardando…" : save === "dirty" ? "Cambios sin guardar" : "Error al guardar"}
          </span>
          {piece.content.isDemo ? <span className="border border-amber px-1.5 py-0.5 font-mono text-[10px] text-amber">DEMO</span> : null}
        </div>
        <ExportPanel projectId={projectId} piece={preview} beforeExport={persist} />
      </header>

      <div className="grid min-h-0 grid-cols-[420px_1fr]">
        <aside className="flex min-h-0 flex-col border-r border-line bg-panel">
          <nav className="flex border-b border-line">
            {(
              [
                ["content", "Noticia"],
                ["design", "Diseño"],
                ["motion", "Movimiento"],
              ] as Array<[Tab, string]>
            ).map(([id, label]) => (
              <button
                key={id}
                onClick={() => setTab(id)}
                className={`flex-1 py-3 text-[13px] transition-colors ${tab === id ? "border-b-2 border-amber font-[700] text-white" : "text-mute hover:text-white"}`}
              >
                {label}
              </button>
            ))}
          </nav>
          {issues.length ? (
            <div className="border-b border-signal/40 bg-signal/10 px-5 py-2 text-[12px] text-signal">
              {issues.map((i) => (
                <div key={i}>{i}</div>
              ))}
            </div>
          ) : null}
          <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">
            {tab === "content" ? <ContentForm piece={piece} update={update} /> : tab === "design" ? <DesignForm piece={piece} update={update} /> : <MotionForm piece={piece} update={update} />}
          </div>
        </aside>
        <main className="min-h-0 bg-ink">
          <PreviewStage piece={preview} />
        </main>
      </div>
    </div>
  );
};
