import React from "react";
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import type { TextBlockLayout } from "../../design/textLayout";
import { roleStyle, textRoles, upper, type TextRole } from "../../design/tokens";
import { type AnimParams, ramp, sec, springAt, useAnimationConfig } from "../timing";
import { TextReveal } from "./TextReveal";

/**
 * NUMBER COUNTER: cuenta hasta el valor con easing, formato es-AR y cifras
 * tabulares. El ancho se reserva con el valor final: no "baila".
 */
export const NumberCounter: React.FC<
  AnimParams & {
    value: number;
    fromValue?: number;
    decimals?: number;
    prefix?: string;
    unit?: string;
    fontSize: number;
    color: string;
    unitColor?: string;
    role?: TextRole;
    style?: React.CSSProperties;
  }
> = ({
  value,
  fromValue = 0,
  decimals = 0,
  prefix = "",
  unit = "",
  fontSize,
  color,
  unitColor,
  role = textRoles.dataNumber,
  delay = 0,
  duration = 1.4,
  easing,
  style,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const cfg = useAnimationConfig();
  const p = ramp(frame, sec(delay, fps, cfg.speed), sec(duration, fps, cfg.speed), easing ?? "snap");
  const fmt = new Intl.NumberFormat("es-AR", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  const current = fromValue + (value - fromValue) * p;
  const unitSize = unit.length > 3 ? 0.32 : 0.5;
  const content = (v: number) => (
    <>
      {prefix ? <span style={{ fontSize: fontSize * 0.55, marginRight: fontSize * 0.04, verticalAlign: "0.62em" }}>{prefix}</span> : null}
      {fmt.format(v)}
      {unit ? (
        <span style={{ fontSize: fontSize * unitSize, marginLeft: fontSize * 0.05, color: unitColor ?? color, letterSpacing: "0" }}>
          {unit}
        </span>
      ) : null}
    </>
  );
  return (
    <div style={{ position: "relative", display: "inline-block", ...roleStyle(role, fontSize), color, fontVariantNumeric: "tabular-nums lining-nums", ...style }}>
      <span style={{ visibility: "hidden" }}>{content(value)}</span>
      <span style={{ position: "absolute", left: 0, top: 0, whiteSpace: "pre" }}>{content(current)}</span>
    </div>
  );
};

/** Pin de ubicacion generico (no es logo de nadie). */
const Pin: React.FC<{ size: number; color: string }> = ({ size, color }) => (
  <svg width={size * 0.76} height={size} viewBox="0 0 19 25" style={{ display: "block" }}>
    <path d="M9.5 0C4.25 0 0 4.2 0 9.4 0 16.4 9.5 25 9.5 25S19 16.4 19 9.4C19 4.2 14.75 0 9.5 0Z" fill={color} />
    <circle cx="9.5" cy="9.4" r="3.6" fill="rgba(0,0,0,0.55)" />
  </svg>
);

/**
 * ANIMATED LOCATION TAG: el pin cae con spring y el texto se despliega con
 * una mascara horizontal.
 */
export const LocationTag: React.FC<
  AnimParams & { text: string; fontSize: number; color: string; pinColor: string; exitAt?: number; style?: React.CSSProperties }
> = ({ text, fontSize, color, pinColor, delay = 0, exitAt, style }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const cfg = useAnimationConfig();
  const start = sec(delay, fps, cfg.speed);
  const drop = springAt(frame, fps, start, { stiffness: 240, damping: 14 });
  const open = ramp(frame, start + sec(0.18, fps, cfg.speed), sec(0.55, fps, cfg.speed), "snap");
  const exit = exitAt !== undefined ? ramp(frame, exitAt, sec(0.3, fps, cfg.speed), "exit") : 0;
  if (frame < start) return null;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: fontSize * 0.42, opacity: 1 - exit, ...style }}>
      <div style={{ translate: `0 ${(1 - drop) * -fontSize * 1.4}px`, opacity: Math.min(1, drop * 2) }}>
        <Pin size={fontSize * 1.18} color={pinColor} />
      </div>
      <div style={{ clipPath: `inset(-20% ${(1 - open) * 100}% -20% 0)` }}>
        <span style={{ ...roleStyle(textRoles.meta, fontSize), color }}>{upper(text)}</span>
      </div>
    </div>
  );
};

/**
 * SPLIT HEADLINE: el titular entra partido en dos mitades horizontales que se
 * desplazan en sentidos opuestos y se ensamblan.
 */
export const SplitHeadline: React.FC<
  AnimParams & { layout: TextBlockLayout; role: TextRole; color: string; accent: string; distance?: number }
> = ({ layout, role, color, accent, delay = 0, duration = 0.7, easing, distance = 240 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const cfg = useAnimationConfig();
  const p = ramp(frame, sec(delay, fps, cfg.speed), sec(duration, fps, cfg.speed), easing ?? "snap");
  const d = (1 - p) * distance * cfg.intensity;
  const half = (clip: string, dx: number) => (
    <div style={{ position: "absolute", inset: 0, clipPath: clip, translate: `${dx}px 0`, opacity: interpolate(p, [0, 0.25], [0, 1], { extrapolateRight: "clamp" }) }}>
      <TextReveal layout={layout} role={role} color={color} accent={accent} mode="none" />
    </div>
  );
  return (
    <div style={{ position: "relative", height: layout.height }}>
      {half("inset(-30% 0 50% 0)", -d)}
      {half("inset(50% 0 -30% 0)", d)}
    </div>
  );
};

/** Indicador "en vivo": punto que late (seno deterministico). */
export const PulseDot: React.FC<{ size: number; color: string }> = ({ size, color }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const phase = (frame / fps) * Math.PI * 2 * 0.9;
  const ring = (Math.sin(phase) + 1) / 2;
  return (
    <div style={{ position: "relative", width: size, height: size }}>
      <div style={{ position: "absolute", inset: 0, borderRadius: "50%", background: color }} />
      <div
        style={{
          position: "absolute",
          inset: -size * 0.45 * ring,
          borderRadius: "50%",
          border: `${Math.max(1, size * 0.12)}px solid ${color}`,
          opacity: 1 - ring,
        }}
      />
    </div>
  );
};
