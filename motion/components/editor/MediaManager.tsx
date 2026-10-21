"use client";

import React, { useRef, useState } from "react";
import { api, probeMedia, toBrowserSrc } from "../../lib/client/api";
import type { Piece } from "../../src/schema/piece";
import { Field, SmallButton, TextInput, Toggle } from "./controls";

type Photo = Piece["content"]["photos"][number];
type Clip = Piece["content"]["videos"][number];

/**
 * Fotos y videos locales: subida, orden, credito y punto de interes (clic sobre
 * la miniatura). El punto de interes guia recortes y movimientos de camara.
 */
export const MediaManager: React.FC<{
  photos: Photo[];
  videos: Clip[];
  onPhotos: (p: Photo[]) => void;
  onVideos: (v: Clip[]) => void;
}> = ({ photos, videos, onPhotos, onVideos }) => {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onFiles = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true);
    setError(null);
    try {
      const newPhotos: Photo[] = [];
      const newVideos: Clip[] = [];
      for (const file of Array.from(files)) {
        const isVideo = file.type.startsWith("video/");
        const up = await api.upload(file);
        const meta = await probeMedia(toBrowserSrc(up.src), isVideo ? "video" : "image").catch(() => null);
        if (isVideo) {
          newVideos.push({ src: up.src, width: meta?.width, height: meta?.height, durationSeconds: meta?.duration, trimStartSeconds: 0, keepAudio: true });
        } else {
          newPhotos.push({ src: up.src, width: meta?.width, height: meta?.height });
        }
      }
      if (newPhotos.length) onPhotos([...photos, ...newPhotos]);
      if (newVideos.length) onVideos([...videos, ...newVideos].slice(0, 1));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };

  const move = (i: number, d: -1 | 1) => {
    const next = [...photos];
    const j = i + d;
    if (j < 0 || j >= next.length) return;
    [next[i], next[j]] = [next[j], next[i]];
    onPhotos(next);
  };

  return (
    <div className="space-y-4">
      <div
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          onFiles(e.dataTransfer.files);
        }}
        onClick={() => input.current?.click()}
        className="cursor-pointer border border-dashed border-line-strong px-4 py-5 text-center transition-colors hover:border-amber"
      >
        <div className="text-[13.5px]">{busy ? "Subiendo…" : "Arrastrá fotos o un video, o hacé clic"}</div>
        <div className="mt-1 font-mono text-[10.5px] uppercase tracking-wider text-mute">JPG · PNG · WEBP · MP4 · MOV · WEBM</div>
        <input ref={input} type="file" multiple accept="image/*,video/*" className="hidden" onChange={(e) => onFiles(e.target.files)} />
      </div>
      {error ? <div className="text-[12px] text-signal">{error}</div> : null}

      {videos.map((v, i) => (
        <div key={v.src} className="border border-line bg-ink p-3">
          <div className="flex items-center justify-between">
            <span className="font-mono text-[10.5px] uppercase tracking-wider text-amber">Video protagonista</span>
            <SmallButton tone="danger" onClick={() => onVideos(videos.filter((_, j) => j !== i))}>
              Quitar
            </SmallButton>
          </div>
          <video src={toBrowserSrc(v.src)} className="mt-2 aspect-video w-full bg-black object-contain" muted />
          <div className="mt-3 grid grid-cols-2 gap-3">
            <Field label="Inicio (s)">
              <input
                className="field"
                type="number"
                min={0}
                step={0.5}
                value={v.trimStartSeconds ?? 0}
                onChange={(e) => onVideos(videos.map((x, j) => (j === i ? { ...x, trimStartSeconds: Math.max(0, Number(e.target.value)) } : x)))}
              />
            </Field>
            <Field label="Duración">
              <div className="field !text-mute">{v.durationSeconds ? `${v.durationSeconds.toFixed(1)} s` : "—"}</div>
            </Field>
          </div>
          <div className="mt-3">
            <Toggle label="Conservar audio original" checked={v.keepAudio ?? true} onChange={(c) => onVideos(videos.map((x, j) => (j === i ? { ...x, keepAudio: c } : x)))} />
          </div>
        </div>
      ))}

      <div className="space-y-3">
        {photos.map((p, i) => (
          <div key={`${p.src}-${i}`} className="flex gap-3 border border-line bg-ink p-2">
            <FocusPicker photo={p} onFocus={(focus) => onPhotos(photos.map((x, j) => (j === i ? { ...x, focus } : x)))} />
            <div className="min-w-0 flex-1 space-y-2">
              <div className="flex items-center justify-between">
                <span className="font-mono text-[10.5px] text-mute">
                  {String(i + 1).padStart(2, "0")} · {p.width && p.height ? `${p.width}×${p.height}` : "sin medidas"}
                </span>
                <div className="flex gap-1">
                  <SmallButton onClick={() => move(i, -1)} disabled={i === 0} title="Subir">
                    ↑
                  </SmallButton>
                  <SmallButton onClick={() => move(i, 1)} disabled={i === photos.length - 1} title="Bajar">
                    ↓
                  </SmallButton>
                  <SmallButton tone="danger" onClick={() => onPhotos(photos.filter((_, j) => j !== i))}>
                    ✕
                  </SmallButton>
                </div>
              </div>
              <TextInput value={p.credit ?? ""} placeholder="Crédito de la foto" onChange={(credit) => onPhotos(photos.map((x, j) => (j === i ? { ...x, credit: credit || undefined } : x)))} />
              <div className="text-[11px] text-mute">Clic en la miniatura: punto de interés.</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

const FocusPicker: React.FC<{ photo: Photo; onFocus: (f: { x: number; y: number }) => void }> = ({ photo, onFocus }) => {
  const focus = photo.focus ?? { x: 0.5, y: 0.42 };
  // La caja respeta la proporcion de la foto: el clic cae sobre la imagen real.
  const aspect = photo.width && photo.height ? photo.width / photo.height : 4 / 3;
  const width = Math.round(Math.min(150, Math.max(56, 86 * aspect)));
  const height = Math.round(width / aspect);
  return (
    <div
      style={{ width, height }}
      className="relative shrink-0 cursor-crosshair overflow-hidden bg-black"
      onClick={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        onFocus({ x: Math.round(((e.clientX - r.left) / r.width) * 100) / 100, y: Math.round(((e.clientY - r.top) / r.height) * 100) / 100 });
      }}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={toBrowserSrc(photo.src)} alt="" className="h-full w-full object-fill" />
      <span className="pointer-events-none absolute h-4 w-4 -translate-x-1/2 -translate-y-1/2 border-2 border-amber" style={{ left: `${focus.x * 100}%`, top: `${focus.y * 100}%` }} />
    </div>
  );
};
