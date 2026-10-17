"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { PieceThumb } from "../components/PieceThumb";
import { api } from "../lib/client/api";
import type { PieceInput, Project, TemplateId } from "../src/schema/piece";

const TEMPLATES: Array<{ id: TemplateId; name: string; demo: string; text: string }> = [
  { id: "breaking", name: "Breaking News", demo: "breaking", text: "Urgencias. Impacto tipográfico, cortes secos, titular condensado." },
  { id: "editorial", name: "Editorial News", demo: "editorial", text: "Noticia general. Serif editorial, panel de papel, cámara lenta." },
  { id: "data", name: "Data Explainer", demo: "data", text: "Cifras protagonistas. Contadores, comparaciones y medidores." },
  { id: "static", name: "Static Post", demo: "staticPortrait", text: "Post estático. Variantes hero, split y tipográfica." },
];

const STATUS: Record<string, string> = {
  draft: "Borrador",
  review: "En revisión",
  approved: "Aprobada",
  published: "Publicada",
  rejected: "Descartada",
};

export default function Dashboard() {
  const router = useRouter();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [inbox, setInbox] = useState<Array<{ file: string; piece: PieceInput; receivedAt: string }>>([]);
  const [wp, setWp] = useState<{ demo: boolean; pieces: PieceInput[] } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setProjects(await api.listProjects());
      setInbox(await api.inbox());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const create = async (body: Parameters<typeof api.createProject>[0], key: string) => {
    setBusy(key);
    setError(null);
    try {
      const p = await api.createProject(body);
      router.push(`/editor/${p.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(null);
    }
  };

  const loadWp = async () => {
    setBusy("wp");
    try {
      setWp(await api.wordpress());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="mx-auto max-w-[1440px] px-8 pb-24">
      <header className="flex items-center justify-between border-b border-line py-6">
        <div className="flex items-center gap-4">
          <div className="grid h-10 w-10 place-items-center bg-violet">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/brand/logo-mark.png" alt="" className="h-6" />
          </div>
          <div>
            <div className="text-[19px] font-[780] tracking-tight" style={{ fontStretch: "87.5%" }}>
              DÚO MOTION
            </div>
            <div className="font-mono text-[10.5px] uppercase tracking-[0.16em] text-mute">Sistema audiovisual · Panel editorial</div>
          </div>
        </div>
        <div className="font-mono text-[11px] text-mute">Local · 127.0.0.1</div>
      </header>

      {error ? <div className="mt-6 border border-signal/50 bg-signal/10 px-4 py-3 text-sm text-signal">{error}</div> : null}

      <section className="mt-10">
        <div className="section-title">Nueva pieza</div>
        <div className="mt-4 grid grid-cols-4 gap-4">
          {TEMPLATES.map((t, i) => (
            <div key={t.id} className="group relative overflow-hidden border border-line bg-panel p-5 transition-colors hover:border-amber/60">
              <div className="font-mono text-[11px] text-mute">{String(i + 1).padStart(2, "0")}</div>
              <div className="mt-6 text-[26px] leading-[0.95] font-[820]" style={{ fontStretch: "75%" }}>
                {t.name.toUpperCase()}
              </div>
              <p className="mt-3 min-h-[40px] text-[13px] leading-snug text-soft">{t.text}</p>
              <div className="mt-5 flex gap-2">
                <button
                  disabled={!!busy}
                  onClick={() =>
                    create(
                      {
                        piece: {
                          content: {
                            id: `n-${Date.now().toString(36)}`,
                            originalTitle: "Título original de la noticia",
                            headline: "Escribí el titular audiovisual",
                            category: "actualidad",
                            date: new Date().toISOString(),
                            source: { name: "Redacción Dúo" },
                            breaking: t.id === "breaking",
                            editorialStatus: "draft",
                          },
                          presentation: { template: t.id, format: t.id === "static" ? "portrait" : "reel", durationSeconds: 15 },
                        },
                        name: `Nueva ${t.name}`,
                      },
                      `new-${t.id}`,
                    )
                  }
                  className="bg-amber px-3 py-1.5 text-[13px] font-[700] text-ink transition-opacity hover:opacity-90 disabled:opacity-40"
                >
                  {busy === `new-${t.id}` ? "Creando…" : "Crear"}
                </button>
                <button
                  disabled={!!busy}
                  onClick={() => create({ demo: t.demo }, `demo-${t.id}`)}
                  className="border border-line-strong px-3 py-1.5 text-[13px] text-soft transition-colors hover:border-amber hover:text-white disabled:opacity-40"
                >
                  {busy === `demo-${t.id}` ? "Abriendo…" : "Desde demo"}
                </button>
              </div>
              <div className="absolute -right-6 -top-6 h-16 w-16 rotate-[36deg] bg-violet/40 transition-colors group-hover:bg-amber/30" />
            </div>
          ))}
        </div>
      </section>

      <section className="mt-12">
        <div className="flex items-end justify-between">
          <div className="section-title">Proyectos</div>
          <button onClick={refresh} className="font-mono text-[11px] text-mute hover:text-white">
            Actualizar
          </button>
        </div>
        {projects === null ? (
          <div className="mt-6 text-sm text-mute">Cargando proyectos…</div>
        ) : projects.length === 0 ? (
          <div className="mt-6 border border-dashed border-line p-10 text-center text-sm text-mute">Todavía no hay proyectos. Creá una pieza o abrí una demo.</div>
        ) : (
          <div className="mt-4 grid grid-cols-6 gap-4">
            {projects.slice(0, 24).map((p) => (
              <div key={p.id} className="group border border-line bg-panel transition-colors hover:border-amber/60">
                <Link href={`/editor/${p.id}`} className="block">
                  <div className="flex h-[260px] items-center justify-center overflow-hidden bg-ink">
                    <PieceThumb piece={p.piece} className="h-full" />
                  </div>
                  <div className="p-3">
                    <div className="line-clamp-2 text-[13px] leading-snug font-[600]">{p.name}</div>
                    <div className="mt-2 flex items-center justify-between font-mono text-[10px] uppercase tracking-wider text-mute">
                      <span>
                        {p.piece.presentation.template} · {p.piece.presentation.format}
                      </span>
                      <span className={p.piece.content.editorialStatus === "approved" ? "text-amber" : ""}>{STATUS[p.piece.content.editorialStatus] ?? ""}</span>
                    </div>
                  </div>
                </Link>
                <div className="flex justify-end border-t border-line px-3 py-1.5 opacity-0 transition-opacity group-hover:opacity-100">
                  <button
                    onClick={async () => {
                      if (!confirm(`¿Eliminar "${p.name}"?`)) return;
                      await api.deleteProject(p.id);
                      refresh();
                    }}
                    className="font-mono text-[10.5px] text-mute hover:text-signal"
                  >
                    Eliminar
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="mt-12 grid grid-cols-2 gap-6">
        <div className="border border-line bg-panel p-5">
          <div className="section-title">Bandeja del pipeline</div>
          <p className="mt-2 text-[13px] text-soft">Piezas que generó el autopublicador. Abrilas para revisar o rehacer una versión manual.</p>
          <div className="scroll-thin mt-4 max-h-[320px] space-y-2 overflow-auto pr-2">
            {inbox.length === 0 ? <div className="text-sm text-mute">Sin piezas recientes.</div> : null}
            {inbox.map((item) => (
              <div key={item.file} className="flex items-center justify-between gap-4 border border-line px-3 py-2">
                <div className="min-w-0">
                  <div className="truncate text-[13px]">{item.piece.content.headline.replace(/\*/g, "")}</div>
                  <div className="font-mono text-[10px] uppercase text-mute">
                    {item.piece.presentation?.template} · {item.piece.content.source?.name}
                  </div>
                </div>
                <button
                  disabled={!!busy}
                  onClick={() => create({ piece: item.piece, origin: "pipeline" }, item.file)}
                  className="shrink-0 border border-line-strong px-2.5 py-1 text-[12px] hover:border-amber"
                >
                  Revisar
                </button>
              </div>
            ))}
          </div>
        </div>
        <div className="border border-line bg-panel p-5">
          <div className="flex items-center justify-between">
            <div className="section-title">WordPress</div>
            <button onClick={loadWp} disabled={!!busy} className="border border-line-strong px-2.5 py-1 text-[12px] hover:border-amber disabled:opacity-40">
              {busy === "wp" ? "Leyendo…" : "Leer notas"}
            </button>
          </div>
          <p className="mt-2 text-[13px] text-soft">Lectura de notas por REST API (WORDPRESS_BASE_URL). Cada nota entra como borrador para revisión.</p>
          {wp?.demo ? <div className="mt-3 font-mono text-[11px] text-amber">Sin WORDPRESS_BASE_URL: mostrando una nota de demostración.</div> : null}
          <div className="scroll-thin mt-4 max-h-[280px] space-y-2 overflow-auto pr-2">
            {wp?.pieces.map((piece) => (
              <div key={piece.content.id} className="flex items-center justify-between gap-4 border border-line px-3 py-2">
                <div className="min-w-0 truncate text-[13px]">{piece.content.originalTitle}</div>
                <button onClick={() => create({ piece, origin: "wordpress" }, piece.content.id)} className="shrink-0 border border-line-strong px-2.5 py-1 text-[12px] hover:border-amber">
                  Importar
                </button>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
