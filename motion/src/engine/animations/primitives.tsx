import React from "react";
import { interpolate, interpolateColors, useCurrentFrame, useVideoConfig } from "remotion";
import { type AnimParams, ramp, sec, springAt, useAnimationConfig } from "../timing";
import { slashClip, slitClip } from "./geometry";

type Box = { width?: number; height?: number };
type WithChildren = { children?: React.ReactNode; style?: React.CSSProperties };

/**
 * MASK WIPE: revela (o retira) el contenido con una barrida diagonal en la
 * pendiente de la marca. `mode="out"` lo retira.
 */
export const MaskWipe: React.FC<
  AnimParams & Box & WithChildren & { mode?: "in" | "out"; from?: "left" | "right" }
> = ({ children, style, width, height, delay = 0, duration = 0.6, easing, mode = "in", from = "left" }) => {
  const frame = useCurrentFrame();
  const { fps, width: W, height: H } = useVideoConfig();
  const cfg = useAnimationConfig();
  const p = ramp(frame, sec(delay, fps, cfg.speed), sec(duration, fps, cfg.speed), easing ?? "glide");
  const progress = mode === "in" ? p : 1 - p;
  const w = width ?? W;
  const h = height ?? H;
  if (progress <= 0) return null;
  return (
    <div style={{ position: "absolute", inset: 0, ...style, clipPath: progress >= 1 ? undefined : slashClip(progress, w, h, from) }}>
      {children}
    </div>
  );
};

/**
 * IMAGE REVEAL: ranura diagonal que se abre desde el centro mientras la imagen
 * se asienta desde una escala mayor. Para revelados fotograficos.
 */
export const ImageReveal: React.FC<AnimParams & Box & WithChildren> = ({
  children,
  style,
  width,
  height,
  delay = 0,
  duration = 0.9,
  easing,
  scaleFrom = 1.28,
  intensity,
}) => {
  const frame = useCurrentFrame();
  const { fps, width: W, height: H } = useVideoConfig();
  const cfg = useAnimationConfig();
  const k = intensity ?? cfg.intensity;
  const start = sec(delay, fps, cfg.speed);
  const p = ramp(frame, start, sec(duration, fps, cfg.speed), easing ?? "snap");
  const settle = ramp(frame, start, sec(duration * 1.8, fps, cfg.speed), "snap");
  const w = width ?? W;
  const h = height ?? H;
  if (p <= 0) return null;
  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden", clipPath: p >= 1 ? undefined : slitClip(p, w, h), ...style }}>
      <div style={{ position: "absolute", inset: 0, scale: String(interpolate(settle, [0, 1], [1 + (scaleFrom - 1) * k, 1])) }}>
        {children}
      </div>
    </div>
  );
};

/**
 * CINEMATIC ZOOM: empuje de camara continuo y suave sobre toda la duracion de
 * la secuencia, anclado al punto de interes.
 */
export const CinematicZoom: React.FC<
  WithChildren & { from?: number; to?: number; focus?: { x: number; y: number }; durationFrames?: number; drift?: number }
> = ({ children, style, from = 1, to, focus = { x: 0.5, y: 0.45 }, durationFrames, drift = 0 }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const cfg = useAnimationConfig();
  const total = durationFrames ?? durationInFrames;
  const end = to ?? cfg.cameraZoom;
  const t = ramp(frame, 0, Math.max(1, total), "glide");
  const scale = from + (end - from) * t;
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        transformOrigin: `${focus.x * 100}% ${focus.y * 100}%`,
        scale: String(scale),
        translate: drift ? `${(t - 0.5) * drift}px 0` : undefined,
        ...style,
      }}
    >
      {children}
    </div>
  );
};

/**
 * PAN & PARALLAX: capas que se desplazan a distinta velocidad. `depth` 0 = fija,
 * 1 = recorre `distance` completa en la duracion.
 */
export const ParallaxLayer: React.FC<
  WithChildren & { depth: number; distance?: number; direction?: "left" | "right" | "up" | "down"; durationFrames?: number }
> = ({ children, style, depth, distance = 120, direction = "left", durationFrames }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const cfg = useAnimationConfig();
  const t = ramp(frame, 0, durationFrames ?? durationInFrames, "glide");
  const d = (t - 0.5) * distance * depth * cfg.intensity;
  const translate =
    direction === "left"
      ? `${-d}px 0`
      : direction === "right"
        ? `${d}px 0`
        : direction === "up"
          ? `0 ${-d}px`
          : `0 ${d}px`;
  return <div style={{ position: "absolute", inset: 0, translate, ...style }}>{children}</div>;
};

/**
 * SCALE TRANSITION: entrada (o salida) por escala con spring. Para impactos.
 */
export const ScaleIn: React.FC<AnimParams & WithChildren & { origin?: string; exitAt?: number }> = ({
  children,
  style,
  delay = 0,
  scaleFrom = 1.6,
  opacityFrom = 0,
  stiffness,
  damping,
  origin = "50% 50%",
  intensity,
  exitAt,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const cfg = useAnimationConfig();
  const k = intensity ?? cfg.intensity;
  const s = springAt(frame, fps, sec(delay, fps, cfg.speed), {
    stiffness: stiffness ?? cfg.stiffness * 1.4,
    damping: damping ?? cfg.damping,
  });
  const exit = exitAt !== undefined ? ramp(frame, exitAt, sec(0.3, fps, cfg.speed), "exit") : 0;
  const scale = interpolate(s, [0, 1], [1 + (scaleFrom - 1) * k, 1]) * (1 - exit * 0.12);
  return (
    <div
      style={{
        transformOrigin: origin,
        scale: String(scale),
        opacity: interpolate(s, [0, 0.35], [opacityFrom, 1], { extrapolateRight: "clamp" }) * (1 - exit),
        ...style,
      }}
    >
      {children}
    </div>
  );
};

/**
 * COLOR TRANSITION: fondo que pasa por una lista de colores en tiempos dados
 * (segundos). Sin gradientes decorativos: color plano con corte suave.
 */
export const ColorField: React.FC<WithChildren & { stops: Array<{ at: number; color: string }>; transition?: number }> = ({
  children,
  style,
  stops,
  transition = 0.35,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  if (stops.length === 0) return null;
  let color = stops[0].color;
  for (let i = 1; i < stops.length; i++) {
    const a = stops[i - 1];
    const b = stops[i];
    const start = b.at * fps;
    if (frame >= start) {
      const p = ramp(frame, start, transition * fps, "glide");
      color = interpolateColors(p, [0, 1], [a.color, b.color]);
    }
  }
  return <div style={{ position: "absolute", inset: 0, background: color, ...style }}>{children}</div>;
};

/** FADE/SLIDE utilitario para elementos menores (etiquetas, meta). */
export const Rise: React.FC<AnimParams & WithChildren & { distance?: number; exitAt?: number }> = ({
  children,
  style,
  delay = 0,
  duration = 0.6,
  easing,
  distance = 28,
  direction = "up",
  exitAt,
  opacityFrom = 0,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const cfg = useAnimationConfig();
  const p = ramp(frame, sec(delay, fps, cfg.speed), sec(duration, fps, cfg.speed), easing ?? cfg.easing);
  const exit = exitAt !== undefined ? ramp(frame, exitAt, sec(0.3, fps, cfg.speed), "exit") : 0;
  const d = (1 - p) * distance * cfg.intensity;
  const translate =
    direction === "up" ? `0 ${d}px` : direction === "down" ? `0 ${-d}px` : direction === "left" ? `${d}px 0` : `${-d}px 0`;
  return (
    <div style={{ opacity: (opacityFrom + (1 - opacityFrom) * p) * (1 - exit), translate, ...style }}>{children}</div>
  );
};

/** Barra que crece (subrayados, reglas, barras de datos). */
export const GrowBar: React.FC<
  AnimParams & { length: number; thickness: number; color: string; axis?: "x" | "y"; origin?: "start" | "end"; style?: React.CSSProperties }
> = ({ length, thickness, color, axis = "x", origin = "start", delay = 0, duration = 0.7, easing, style }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const cfg = useAnimationConfig();
  const p = ramp(frame, sec(delay, fps, cfg.speed), sec(duration, fps, cfg.speed), easing ?? "snap");
  return (
    <div
      style={{
        width: axis === "x" ? length : thickness,
        height: axis === "x" ? thickness : length,
        background: color,
        transformOrigin: axis === "x" ? (origin === "start" ? "left center" : "right center") : origin === "start" ? "center bottom" : "center top",
        scale: axis === "x" ? `${p} 1` : `1 ${p}`,
        ...style,
      }}
    />
  );
};
