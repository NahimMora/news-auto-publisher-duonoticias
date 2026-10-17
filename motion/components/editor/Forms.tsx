"use client";

import React from "react";
import { categories, type CategoryId } from "../../src/brand/categories";
import { hooks } from "../../src/engine/hooks/registry";
import type { Piece, Stat } from "../../src/schema/piece";
import { listTemplates } from "../../src/templates/registry";
import { Field, Section, Segmented, Select, Slider, SmallButton, TextArea, TextInput, Toggle } from "./controls";
import { HeadlineCheck } from "./HeadlineCheck";
import { MediaManager } from "./MediaManager";

type Props = { piece: Piece; update: (fn: (draft: Piece) => void) => void };

const toLocalInput = (iso: string) => {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const off = d.getTimezoneOffset();
  return new Date(d.getTime() - off * 60000).toISOString().slice(0, 16);
};

/** CONTENIDO: lo que informa la noticia. Nunca lo cambia una decision visual. */
export const ContentForm: React.FC<Props> = ({ piece, update }) => {
  const c = piece.content;
  return (
    <>
      <Section title="Noticia">
        <Field label="Título original" hint="Tal como lo publicó la fuente. Referencia, no se muestra en pantalla.">
          <TextArea rows={2} value={c.originalTitle} onChange={(v) => update((d) => void (d.content.originalTitle = v))} />
        </Field>
        <Field label="Titular audiovisual" hint="Marcá *una palabra* con asteriscos para enfatizarla.">
          <TextArea large rows={3} value={c.headline} onChange={(v) => update((d) => void (d.content.headline = v))} />
          <HeadlineCheck piece={piece} onApply={(h) => update((d) => void (d.content.headline = h))} />
        </Field>
        <Field label="Bajada">
          <TextArea rows={3} value={c.deck} onChange={(v) => update((d) => void (d.content.deck = v))} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Categoría">
            <Select<CategoryId>
              value={c.category}
              options={Object.entries(categories).map(([value, cat]) => ({ value: value as CategoryId, label: cat.label }))}
              onChange={(v) => update((d) => void (d.content.category = v))}
            />
          </Field>
          <Field label="Ubicación">
            <TextInput value={c.location ?? ""} placeholder="Salta Capital" onChange={(v) => update((d) => void (d.content.location = v || undefined))} />
          </Field>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Fecha y hora">
            <input
              className="field"
              type="datetime-local"
              value={toLocalInput(c.date)}
              onChange={(e) => update((d) => void (d.content.date = new Date(e.target.value).toISOString()))}
            />
          </Field>
          <Field label="Fuente">
            <TextInput value={c.source.name} onChange={(v) => update((d) => void (d.content.source.name = v))} />
          </Field>
        </div>
        <Toggle label="Último momento" hint="Activa la etiqueta de urgencia." checked={c.breaking} onChange={(v) => update((d) => void (d.content.breaking = v))} />
      </Section>

      <Section title="Fotos y video">
        <MediaManager
          photos={c.photos}
          videos={c.videos}
          onPhotos={(p) => update((d) => void (d.content.photos = p))}
          onVideos={(v) => update((d) => void (d.content.videos = v))}
        />
      </Section>

      <Section
        title="Puntos clave"
        aside={
          c.highlights.length < 4 ? (
            <SmallButton onClick={() => update((d) => void d.content.highlights.push(""))}>Agregar</SmallButton>
          ) : null
        }
      >
        {c.highlights.length === 0 ? <div className="text-[12.5px] text-mute">Opcional. Datos concretos tomados de la nota.</div> : null}
        {c.highlights.map((h, i) => (
          <div key={i} className="flex gap-2">
            <TextArea rows={2} value={h} onChange={(v) => update((d) => void (d.content.highlights[i] = v))} />
            <SmallButton tone="danger" onClick={() => update((d) => void d.content.highlights.splice(i, 1))}>
              ✕
            </SmallButton>
          </div>
        ))}
      </Section>

      <Section
        title="Cifras"
        aside={
          c.stats.length < 4 ? (
            <SmallButton onClick={() => update((d) => void d.content.stats.push({ label: "", value: 0, decimals: 0 }))}>Agregar</SmallButton>
          ) : null
        }
      >
        <div className="text-[12px] leading-snug text-mute">Solo cifras que figuran en la nota. La plantilla de datos nunca completa ni estima valores.</div>
        {c.stats.map((s, i) => (
          <StatRow
            key={i}
            stat={s}
            onChange={(next) => update((d) => void (d.content.stats[i] = next))}
            onRemove={() => update((d) => void d.content.stats.splice(i, 1))}
          />
        ))}
      </Section>

      <Section title="Cita">
        <Field label="Texto">
          <TextArea
            rows={2}
            value={c.quote?.text ?? ""}
            onChange={(v) => update((d) => void (d.content.quote = v ? { text: v, author: d.content.quote?.author ?? "" } : undefined))}
          />
        </Field>
        <Field label="Autor">
          <TextInput value={c.quote?.author ?? ""} onChange={(v) => update((d) => void (d.content.quote = d.content.quote ? { ...d.content.quote, author: v } : undefined))} />
        </Field>
      </Section>

      <Section title="Estado editorial">
        <Segmented
          value={c.editorialStatus}
          options={[
            { value: "draft", label: "Borrador" },
            { value: "review", label: "Revisión" },
            { value: "approved", label: "Aprobada" },
            { value: "rejected", label: "Descartada" },
          ]}
          onChange={(v) => update((d) => void (d.content.editorialStatus = v))}
        />
      </Section>
    </>
  );
};

const StatRow: React.FC<{ stat: Stat; onChange: (s: Stat) => void; onRemove: () => void }> = ({ stat, onChange, onRemove }) => (
  <div className="space-y-2 border border-line bg-ink p-3">
    <div className="grid grid-cols-[70px_1fr_70px] gap-2">
      <TextInput value={stat.prefix ?? ""} placeholder="$" onChange={(v) => onChange({ ...stat, prefix: v || undefined })} />
      <input className="field" type="number" value={stat.value} onChange={(e) => onChange({ ...stat, value: Number(e.target.value) })} />
      <TextInput value={stat.unit ?? ""} placeholder="%" onChange={(v) => onChange({ ...stat, unit: v || undefined })} />
    </div>
    <TextInput value={stat.label} placeholder="Qué mide la cifra" onChange={(v) => onChange({ ...stat, label: v })} />
    <div className="grid grid-cols-[1fr_1fr_auto] gap-2">
      <input
        className="field"
        type="number"
        placeholder="Comparar con"
        value={stat.compareValue ?? ""}
        onChange={(e) => onChange({ ...stat, compareValue: e.target.value === "" ? undefined : Number(e.target.value) })}
      />
      <TextInput value={stat.compareLabel ?? ""} placeholder="Ej. Año anterior" onChange={(v) => onChange({ ...stat, compareLabel: v || undefined })} />
      <SmallButton tone="danger" onClick={onRemove}>
        ✕
      </SmallButton>
    </div>
  </div>
);

/** PRESENTACION: decisiones visuales. */
export const DesignForm: React.FC<Props> = ({ piece, update }) => {
  const p = piece.presentation;
  const templates = listTemplates();
  const isStill = p.template === "static";
  const video = piece.content.videos[0];
  return (
    <>
      <Section title="Plantilla">
        <div className="grid grid-cols-2 gap-2">
          {templates.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() =>
                update((d) => {
                  d.presentation.template = t.id;
                  if (t.id === "static" && d.presentation.format === "reel") d.presentation.format = "portrait";
                })
              }
              className={`border p-3 text-left transition-colors ${p.template === t.id ? "border-amber bg-amber/10" : "border-line hover:border-line-strong"}`}
            >
              <div className="text-[14px] font-[760]" style={{ fontStretch: "87.5%" }}>
                {t.label}
              </div>
              <div className="mt-1 text-[11.5px] leading-snug text-mute">{t.description}</div>
            </button>
          ))}
        </div>
      </Section>
      <Section title="Formato">
        <Segmented
          value={p.format}
          options={[
            { value: "reel", label: "9:16", title: "Reel / Story 1080×1920" },
            { value: "portrait", label: "4:5", title: "Post vertical 1080×1350" },
            { value: "square", label: "1:1", title: "Post cuadrado 1080×1080" },
          ]}
          onChange={(v) => update((d) => void (d.presentation.format = v))}
        />
        {isStill ? (
          <Field label="Variante">
            <Segmented
              value={p.staticVariant}
              options={[
                { value: "auto", label: "Auto" },
                { value: "hero", label: "Hero" },
                { value: "split", label: "Split" },
                { value: "type", label: "Tipo" },
              ]}
              onChange={(v) => update((d) => void (d.presentation.staticVariant = v))}
            />
          </Field>
        ) : null}
      </Section>
      {!isStill ? (
        <Section title="Gancho (primeros segundos)">
          <div className="grid grid-cols-2 gap-2">
            {[{ id: "auto" as const, label: "Automático", description: "Elige el gancho según el contenido." }, ...hooks].map((h) => {
              const usable = h.id === "auto" || ("suits" in h && h.suits(piece.content, p.template) > 0);
              return (
                <button
                  key={h.id}
                  type="button"
                  disabled={!usable}
                  onClick={() => update((d) => void (d.presentation.hook = h.id))}
                  className={`border p-3 text-left transition-colors disabled:opacity-35 ${p.hook === h.id ? "border-amber bg-amber/10" : "border-line hover:border-line-strong"}`}
                >
                  <div className="text-[13px] font-[700]">{h.label}</div>
                  <div className="mt-1 text-[11px] leading-snug text-mute">{usable ? h.description : "No aplica a este contenido."}</div>
                </button>
              );
            })}
          </div>
        </Section>
      ) : null}
      {!isStill ? (
        <Section title="Duración">
          <Slider
            label="Segundos"
            value={p.durationSeconds}
            min={6}
            max={video?.durationSeconds ? Math.min(180, Math.floor(video.durationSeconds)) : 60}
            step={1}
            format={(v) => `${v} s`}
            onChange={(v) => update((d) => void (d.presentation.durationSeconds = v))}
          />
          {video?.durationSeconds ? <div className="text-[11.5px] text-mute">Con video, la pieza no supera la duración del clip.</div> : null}
        </Section>
      ) : null}
      <Section title="Color y tema">
        <Field label="Acento">
          <div className="flex items-center gap-2">
            <input
              type="color"
              value={p.accent || "#ffb700"}
              onChange={(e) => update((d) => void (d.presentation.accent = e.target.value))}
              className="h-9 w-12 cursor-pointer border border-line bg-ink"
            />
            <SmallButton onClick={() => update((d) => void (d.presentation.accent = undefined))}>Usar el de la categoría</SmallButton>
          </div>
        </Field>
        {p.template === "editorial" ? (
          <Field label="Panel editorial">
            <Segmented
              value={p.theme}
              options={[
                { value: "light", label: "Papel" },
                { value: "dark", label: "Oscuro" },
              ]}
              onChange={(v) => update((d) => void (d.presentation.theme = v))}
            />
          </Field>
        ) : null}
      </Section>
    </>
  );
};

/** MOVIMIENTO: parametros del motor de animacion. */
export const MotionForm: React.FC<Props> = ({ piece, update }) => {
  const a = piece.presentation.animation;
  const set = (key: keyof typeof a, value: number | string) =>
    update((d) => {
      (d.presentation.animation as Record<string, unknown>)[key] = value;
    });
  return (
    <Section title="Motor de animación">
      <Slider label="Intensidad" value={a.intensity} min={0} max={1.6} step={0.05} onChange={(v) => set("intensity", v)} format={(v) => v.toFixed(2)} />
      <Slider label="Velocidad" value={a.speed} min={0.6} max={1.6} step={0.05} onChange={(v) => set("speed", v)} format={(v) => `${v.toFixed(2)}×`} />
      <Field label="Curva de entrada">
        <Segmented
          value={a.easing}
          options={[
            { value: "snap", label: "Snap" },
            { value: "glide", label: "Glide" },
            { value: "punch", label: "Punch" },
            { value: "linear", label: "Lineal" },
          ]}
          onChange={(v) => set("easing", v)}
        />
      </Field>
      <Slider label="Spring · rigidez" value={a.stiffness} min={20} max={400} step={5} onChange={(v) => set("stiffness", v)} />
      <Slider label="Spring · amortiguación" value={a.damping} min={6} max={200} step={1} onChange={(v) => set("damping", v)} />
      <Slider label="Zoom de cámara" value={a.cameraZoom} min={1} max={1.4} step={0.01} onChange={(v) => set("cameraZoom", v)} format={(v) => `${Math.round((v - 1) * 100)} %`} />
      <SmallButton
        onClick={() =>
          update((d) => {
            d.presentation.animation = { intensity: 1, speed: 1, easing: "snap", stiffness: 170, damping: 22, cameraZoom: 1.12 };
          })
        }
      >
        Restablecer
      </SmallButton>
    </Section>
  );
};
