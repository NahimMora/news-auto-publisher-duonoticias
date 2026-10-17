import React from "react";
import { interpolateColors, useCurrentFrame, useVideoConfig } from "remotion";
import type { TextBlockLayout, Token } from "../../design/textLayout";
import { roleStyle, type TextRole } from "../../design/tokens";
import { type AnimParams, easings, ramp, sec, springAt, useAnimationConfig } from "../timing";

export type RevealMode = "line" | "word" | "char" | "none";
export type EmphasisStyle = "color" | "marker" | "italic";

export type TextRevealProps = AnimParams & {
  layout: TextBlockLayout;
  role: TextRole;
  color: string;
  accent: string;
  mode?: RevealMode;
  /** Segundos entre unidades (linea/palabra/caracter). */
  stagger?: number;
  align?: "left" | "center" | "right";
  emphasisStyle?: EmphasisStyle;
  /** Color del texto enfatizado cuando emphasisStyle = marker. */
  markerTextColor?: string;
  /** Frame relativo en el que el bloque empieza a salir (opcional). */
  exitAt?: number;
  exitDuration?: number;
  style?: React.CSSProperties;
  /** Usar spring en lugar de easing para cada unidad. */
  physics?: boolean;
};

/**
 * Bloque de texto compuesto (lineas ya calculadas) con revelado por linea,
 * palabra o caracter. Cada linea vive dentro de una mascara: el texto entra
 * desde fuera del recorte, como en grafica broadcast, no con un fade.
 */
export const TextReveal: React.FC<TextRevealProps> = ({
  layout,
  role,
  color,
  accent,
  mode = "line",
  stagger,
  align = "left",
  emphasisStyle = "color",
  markerTextColor,
  delay = 0,
  duration,
  easing,
  intensity,
  direction = "up",
  stiffness,
  damping,
  physics = false,
  exitAt,
  exitDuration = 0.35,
  style,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const cfg = useAnimationConfig();
  const k = intensity ?? cfg.intensity;
  const ease = easing ?? cfg.easing;
  const speed = cfg.speed;
  const start = sec(delay, fps, speed);
  const unitDuration = sec(duration ?? (mode === "char" ? 0.42 : mode === "word" ? 0.55 : 0.7), fps, speed);
  const unitStagger = sec(stagger ?? (mode === "char" ? 0.016 : mode === "word" ? 0.05 : 0.085), fps, speed) || 1;

  const exitP = exitAt !== undefined ? ramp(frame, exitAt, sec(exitDuration, fps, speed), "exit") : 0;

  const progressFor = (index: number) => {
    if (mode === "none") return 1;
    const s = start + index * unitStagger;
    return physics
      ? springAt(frame, fps, s, { stiffness: stiffness ?? cfg.stiffness, damping: damping ?? cfg.damping })
      : ramp(frame, s, unitDuration, ease);
  };

  // Mascara con aire para acentos en mayusculas (Á, Ñ) y descendentes.
  const padTop = 0.24;
  const padBottom = 0.16;
  // Desplazamiento oculto en px: el glifo (con tilde) queda entero fuera de la mascara.
  const hiddenPx = layout.lineHeightPx + (padTop + padBottom + 0.12) * layout.fontSize;
  const offsetFor = (p: number, full = true) => {
    const d = (1 - p) * (full ? hiddenPx : hiddenPx * Math.max(0.35, k));
    switch (direction) {
      case "down":
        return `0 ${-d}px`;
      case "left":
        return `${d * 2}px 0`;
      case "right":
        return `${-d * 2}px 0`;
      default:
        return `0 ${d}px`;
    }
  };

  const base = roleStyle(role, layout.fontSize);
  let unitIndex = 0;
  let charIndex = 0;

  const renderToken = (t: Token, i: number, line: Token[]) => {
    const isLast = i === line.length - 1;
    const text = t.text + (isLast ? "" : " ");
    const markerP = mode === "none" ? 1 : t.emphasis && emphasisStyle === "marker" ? ramp(frame, start + unitDuration * 0.35, sec(0.38, fps, speed), "glide") : 0;
    const tokenStyle: React.CSSProperties = t.emphasis
      ? emphasisStyle === "italic"
        ? { fontStyle: "italic", color: accent }
        : emphasisStyle === "marker"
          ? { color: interpolateColors(markerP, [0, 0.6], [color, markerTextColor ?? color]) }
          : { color: accent }
      : {};
    const marker =
      t.emphasis && emphasisStyle === "marker" ? (
        <span
          aria-hidden
          style={{
            position: "absolute",
            left: "-0.06em",
            right: isLast ? "-0.06em" : "0.18em",
            // Cubre las tildes de mayusculas (TELEFÉRICO): el texto enfatizado es oscuro.
            top: "-0.14em",
            bottom: "0.02em",
            background: accent,
            transformOrigin: "left center",
            scale: `${markerP} 1`,
            zIndex: -1,
          }}
        />
      ) : null;

    if (mode === "word") {
      const p = progressFor(unitIndex++);
      return (
        <span key={i} style={{ display: "inline-block", position: "relative", isolation: "isolate", ...tokenStyle }}>
          {marker}
          <span
            style={{
              display: "inline-block",
              translate: offsetFor(p),
              rotate: `${(1 - p) * 7 * k}deg`,
              transformOrigin: "left bottom",
            }}
          >
            {text}
          </span>
        </span>
      );
    }
    if (mode === "char") {
      return (
        <span key={i} style={{ display: "inline-block", position: "relative", isolation: "isolate", ...tokenStyle }}>
          {marker}
          {Array.from(text).map((ch, ci) => {
            const p = progressFor(charIndex++);
            return (
              <span
                key={ci}
                style={{
                  display: "inline-block",
                  opacity: p,
                  translate: `0 ${(1 - p) * 0.45 * k}em`,
                  whiteSpace: "pre",
                }}
              >
                {ch}
              </span>
            );
          })}
        </span>
      );
    }
    return (
      <span key={i} style={{ position: "relative", isolation: "isolate", display: "inline-block", ...tokenStyle }}>
        {marker}
        {text}
      </span>
    );
  };

  return (
    <div
      style={{
        ...base,
        color,
        textAlign: align,
        width: "100%",
        opacity: 1 - exitP,
        translate: exitP ? `0 ${-exitP * 0.35 * layout.fontSize}px` : undefined,
        ...style,
      }}
    >
      {layout.lines.map((line, li) => {
        const lineP = mode === "line" ? progressFor(li) : 1;
        if (mode === "line") unitIndex++;
        return (
          <div
            key={li}
            style={{
              overflow: "hidden",
              height: layout.lineHeightPx + (padTop + padBottom) * layout.fontSize,
              paddingTop: padTop * layout.fontSize,
              marginTop: li === 0 ? -padTop * layout.fontSize : -(padTop + padBottom) * layout.fontSize,
              marginBottom: 0,
              // El ultimo margen inferior compensa el padding agregado.
              ...(li === layout.lines.length - 1 ? { marginBottom: -padBottom * layout.fontSize } : null),
            }}
          >
            <div
              style={{
                translate: mode === "line" ? offsetFor(lineP) : undefined,
                height: layout.lineHeightPx,
                lineHeight: `${layout.lineHeightPx}px`,
              }}
            >
              {line.tokens.map((t, i) => renderToken(t, i, line.tokens))}
            </div>
          </div>
        );
      })}
    </div>
  );
};

/** Exportado para presets que quieren el mismo easing fuera del componente. */
export const textEasing = easings;
