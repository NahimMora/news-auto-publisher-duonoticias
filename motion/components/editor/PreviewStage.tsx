"use client";

import { Player, Thumbnail, type PlayerRef } from "@remotion/player";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { toPlayerPiece } from "../../lib/client/api";
import { resolveHook } from "../../src/engine/hooks/registry";
import { planTimeline } from "../../src/engine/timeline";
import { FPS, PieceComposition, pieceDimensions, pieceDurationInFrames } from "../../src/PieceComposition";
import type { Piece } from "../../src/schema/piece";
import { OUTRO_SECONDS } from "../../src/templates/shared";
import { isStillTemplate } from "../../src/templates/meta";

const BEAT_LABEL: Record<string, string> = {
  headline: "Titular",
  deck: "Bajada",
  highlight: "Clave",
  stat: "Cifra",
  quote: "Cita",
  hold: "Titular fijo",
};

/**
 * Previsualizacion protagonista: Remotion Player (video) o Thumbnail (post) y
 * debajo la estructura de tiempos real de la pieza; clic en un tramo = saltar.
 */
export const PreviewStage: React.FC<{ piece: Piece }> = ({ piece }) => {
  const playerRef = useRef<PlayerRef>(null);
  const [frame, setFrame] = useState(0);
  const p = useMemo(() => toPlayerPiece(piece), [piece]);
  const { width, height } = pieceDimensions(p);
  const duration = pieceDurationInFrames(p);
  const still = isStillTemplate(p.presentation.template);

  const plan = useMemo(() => {
    if (still) return null;
    const hook = resolveHook(p.presentation.hook, p.content, p.presentation.template);
    return {
      hookDef: hook,
      ...planTimeline({
        content: p.content,
        template: p.presentation.template,
        fps: FPS,
        totalFrames: duration,
        hookSeconds: hook.seconds,
        outroSeconds: OUTRO_SECONDS,
        videoLed: p.content.videos.length > 0,
        skipFirstStat: hook.id === "data",
      }),
    };
  }, [p, duration, still]);

  useEffect(() => {
    const player = playerRef.current;
    if (!player) return;
    const onFrame = (e: { detail: { frame: number } }) => setFrame(e.detail.frame);
    player.addEventListener("frameupdate", onFrame);
    return () => player.removeEventListener("frameupdate", onFrame);
  }, [still]);

  const segments = plan
    ? [
        { label: `Gancho · ${plan.hookDef.label}`, start: 0, duration: plan.hook.duration, tone: "bg-amber text-ink" },
        ...plan.beats.map((b) => ({ label: BEAT_LABEL[b.kind] ?? b.kind, start: b.start, duration: b.duration, tone: "bg-violet-hi text-white" })),
        { label: "Cierre", start: plan.outro.start, duration: plan.outro.duration, tone: "bg-line-strong text-white" },
      ]
    : [];

  return (
    <div className="flex h-full flex-col">
      <div className="relative flex min-h-0 flex-1 items-center justify-center p-6">
        <div className="relative h-full max-h-full" style={{ aspectRatio: `${width} / ${height}` }}>
          {still ? (
            <Thumbnail
              component={PieceComposition}
              inputProps={{ piece: p }}
              compositionWidth={width}
              compositionHeight={height}
              durationInFrames={1}
              fps={FPS}
              frameToDisplay={0}
              style={{ width: "100%", height: "100%", boxShadow: "0 0 0 1px #2a2335" }}
            />
          ) : (
            <Player
              ref={playerRef}
              component={PieceComposition}
              inputProps={{ piece: p }}
              compositionWidth={width}
              compositionHeight={height}
              durationInFrames={duration}
              fps={FPS}
              controls
              loop
              clickToPlay
              showVolumeControls
              acknowledgeRemotionLicense
              style={{ width: "100%", height: "100%", boxShadow: "0 0 0 1px #2a2335" }}
            />
          )}
        </div>
      </div>
      <div className="border-t border-line px-6 py-3">
        <div className="mb-2 flex items-center justify-between font-mono text-[10.5px] uppercase tracking-wider text-mute">
          <span>
            {width}×{height} · {still ? "imagen" : `${(duration / FPS).toFixed(1)} s · ${FPS} fps`}
          </span>
          {!still ? <span className="text-white">{(frame / FPS).toFixed(2)} s</span> : null}
        </div>
        {!still ? (
          <div className="relative flex h-9 w-full gap-px">
            {segments.map((s, i) => (
              <button
                key={i}
                type="button"
                title={s.label}
                onClick={() => playerRef.current?.seekTo(s.start + 2)}
                className={`truncate px-2 text-left text-[11px] font-[600] ${s.tone} opacity-85 transition-opacity hover:opacity-100`}
                style={{ width: `${(s.duration / duration) * 100}%` }}
              >
                {s.label}
              </button>
            ))}
            <div className="pointer-events-none absolute -top-1 bottom-[-4px] w-[2px] bg-white" style={{ left: `${(frame / Math.max(1, duration - 1)) * 100}%` }} />
          </div>
        ) : (
          <div className="text-[12px] text-mute">Post estático: la variante se elige según foto y largo del titular (o la fijás en Diseño).</div>
        )}
      </div>
    </div>
  );
};
