import { createContext, useContext } from "react";
import { Easing, interpolate, spring } from "remotion";
import type { AnimationConfig } from "../schema/piece";

/**
 * Nucleo deterministico del motor: todo depende solo del frame actual.
 * Nada de CSS transitions, timers ni Math.random().
 */

export const easings = {
  /** Entrada rapida con frenado largo: titulares, etiquetas. */
  snap: Easing.bezier(0.16, 1, 0.3, 1),
  /** Movimiento simetrico y suave: camara, paneles editoriales. */
  glide: Easing.bezier(0.65, 0, 0.35, 1),
  /** Golpe con leve sobrepaso: impactos tipograficos. */
  punch: Easing.bezier(0.2, 1.35, 0.35, 1),
  /** Salidas: acelera y desaparece. */
  exit: Easing.bezier(0.7, 0, 0.84, 0),
  linear: Easing.linear,
} as const;

export type EasingName = keyof typeof easings;

export const DEFAULT_ANIMATION: AnimationConfig = {
  intensity: 1,
  speed: 1,
  easing: "snap",
  stiffness: 170,
  damping: 22,
  cameraZoom: 1.12,
};

export const AnimationContext = createContext<AnimationConfig>(DEFAULT_ANIMATION);
export const useAnimationConfig = () => useContext(AnimationContext);

/** Parametros comunes a todas las animaciones (todos opcionales). */
export type AnimParams = {
  /** Segundos desde el inicio de la secuencia. */
  delay?: number;
  /** Segundos. */
  duration?: number;
  easing?: EasingName;
  /** Multiplica desplazamientos/escalas. */
  intensity?: number;
  direction?: "up" | "down" | "left" | "right";
  stiffness?: number;
  damping?: number;
  opacityFrom?: number;
  scaleFrom?: number;
};

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

/** Progreso 0..1 con easing entre [start, start+duration] en frames. */
export const ramp = (frame: number, start: number, duration: number, easing: EasingName = "snap"): number =>
  duration <= 0
    ? frame >= start
      ? 1
      : 0
    : interpolate(frame, [start, start + duration], [0, 1], { ...clamp, easing: easings[easing] });

/** Progreso con spring fisico, deterministico. */
export const springAt = (
  frame: number,
  fps: number,
  start: number,
  cfg: { stiffness?: number; damping?: number; mass?: number; durationInFrames?: number } = {},
): number =>
  spring({
    frame: frame - start,
    fps,
    config: { stiffness: cfg.stiffness ?? 170, damping: cfg.damping ?? 22, mass: cfg.mass ?? 1 },
    durationInFrames: cfg.durationInFrames,
  });

/** Convierte segundos a frames aplicando la velocidad global. */
export const sec = (seconds: number, fps: number, speed = 1) => Math.round((seconds * fps) / speed);

export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

/** Pseudoaleatorio deterministico por semilla (para variaciones controladas). */
export const seeded = (seed: string | number) => {
  let h = 2166136261;
  const s = String(seed);
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return ((h >>> 0) % 10000) / 10000;
};

/** Visibilidad de un tramo con entrada y salida (para capas que entran y salen). */
export const inOut = (
  frame: number,
  start: number,
  end: number,
  inFrames: number,
  outFrames: number,
  easingIn: EasingName = "snap",
): { inP: number; outP: number; visible: boolean } => ({
  inP: ramp(frame, start, inFrames, easingIn),
  outP: ramp(frame, end - outFrames, outFrames, "exit"),
  visible: frame >= start && frame < end,
});
