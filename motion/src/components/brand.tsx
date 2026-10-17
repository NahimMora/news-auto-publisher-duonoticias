import React from "react";
import { AbsoluteFill, Img, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { brand } from "../brand/brand.config";
import { measure } from "../design/textLayout";
import { roleStyle, textRoles, upper } from "../design/tokens";
import { parallelogram, slashRun } from "../engine/animations/geometry";
import { PulseDot } from "../engine/animations/editorial";
import { ramp, sec, useAnimationConfig } from "../engine/timing";

/** Logo del medio. Nunca compite con la noticia: tamano chico y opacidad alta. */
export const BrandLogo: React.FC<{
  variant?: "horizontal" | "mark";
  height: number;
  opacity?: number;
  style?: React.CSSProperties;
}> = ({ variant = "horizontal", height, opacity = 1, style }) => {
  const src = variant === "horizontal" ? brand.logos.horizontal : brand.logos.mark;
  const aspect = variant === "horizontal" ? brand.logos.horizontalAspect : brand.logos.markAspect;
  return <Img src={staticFile(src)} style={{ height, width: height * aspect, opacity, display: "block", ...style }} />;
};

/** Etiqueta de categoria: paralelogramo con la pendiente de la marca. */
export const CategoryTag: React.FC<{
  label: string;
  accent: string;
  fontSize: number;
  textColor?: string;
  delay?: number;
  exitAt?: number;
  style?: React.CSSProperties;
}> = ({ label, accent, fontSize, textColor = brand.colors.ink, delay = 0, exitAt, style }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const cfg = useAnimationConfig();
  const start = sec(delay, fps, cfg.speed);
  const p = ramp(frame, start, sec(0.5, fps, cfg.speed), "snap");
  const textP = ramp(frame, start + sec(0.12, fps, cfg.speed), sec(0.45, fps, cfg.speed), "snap");
  const exit = exitAt !== undefined ? ramp(frame, exitAt, sec(0.28, fps, cfg.speed), "exit") : 0;
  const h = fontSize * 1.9;
  const run = slashRun(h);
  const text = upper(label);
  const w = measure(text, textRoles.kicker, fontSize) + run * 2 + fontSize * 1.0;
  if (frame < start) return null;
  return (
    <div style={{ position: "relative", width: w, height: h, opacity: 1 - exit, ...style }}>
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: accent,
          clipPath: parallelogram(w, h),
          transformOrigin: "left center",
          scale: `${p} 1`,
        }}
      />
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          alignItems: "center",
          paddingLeft: run + fontSize * 0.5,
          overflow: "hidden",
        }}
      >
        <span style={{ ...roleStyle(textRoles.kicker, fontSize), color: textColor, translate: `0 ${(1 - textP) * 110}%` }}>{text}</span>
      </div>
    </div>
  );
};

/** Etiqueta de ULTIMO MOMENTO con punto en vivo. */
export const BreakingLabel: React.FC<{ fontSize: number; delay?: number; label?: string; style?: React.CSSProperties }> = ({
  fontSize,
  delay = 0,
  label = brand.copy.breakingLabel,
  style,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const cfg = useAnimationConfig();
  const start = sec(delay, fps, cfg.speed);
  const p = ramp(frame, start, sec(0.45, fps, cfg.speed), "snap");
  if (frame < start) return null;
  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: fontSize * 0.55,
        background: brand.colors.signal,
        padding: `${fontSize * 0.42}px ${fontSize * 0.7}px ${fontSize * 0.42}px ${fontSize * 0.55}px`,
        clipPath: `inset(0 ${(1 - p) * 100}% 0 0)`,
        ...style,
      }}
    >
      <PulseDot size={fontSize * 0.5} color={brand.colors.white} />
      <span style={{ ...roleStyle(textRoles.kicker, fontSize), color: brand.colors.white }}>{label}</span>
    </div>
  );
};

const dateFmt = new Intl.DateTimeFormat("es-AR", {
  day: "2-digit",
  month: "short",
  year: "numeric",
  timeZone: "America/Argentina/Salta",
});
const timeFmt = new Intl.DateTimeFormat("es-AR", {
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "America/Argentina/Salta",
});

export const formatNewsDate = (iso: string, withTime = true): string => {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const date = dateFmt.format(d).replace(/\./g, "").replace(/ de /g, " ");
  return withTime ? `${date} · ${timeFmt.format(d)} h` : date;
};

/** Linea de metadatos: fecha y fuente en mono. */
export const MetaLine: React.FC<{
  date?: string;
  source?: string;
  fontSize: number;
  color: string;
  separatorColor?: string;
  style?: React.CSSProperties;
}> = ({ date, source, fontSize, color, separatorColor, style }) => {
  const parts: string[] = [];
  if (date) parts.push(formatNewsDate(date));
  if (source) parts.push(`${brand.copy.sourcePrefix}: ${source}`);
  return (
    <div style={{ display: "flex", gap: fontSize * 0.8, alignItems: "center", ...roleStyle(textRoles.meta, fontSize), color, ...style }}>
      {parts.map((p, i) => (
        <React.Fragment key={i}>
          {i > 0 ? <span style={{ width: fontSize * 0.9, height: Math.max(2, fontSize * 0.09), background: separatorColor ?? color, opacity: 0.6 }} /> : null}
          <span>{upper(p)}</span>
        </React.Fragment>
      ))}
    </div>
  );
};

/** Marca visible en piezas de demostracion: nunca se confunde con una noticia real. */
export const DemoBadge: React.FC<{ fontSize: number; top: number; right: number }> = ({ fontSize, top, right }) => (
  <div
    style={{
      position: "absolute",
      top,
      right,
      zIndex: 50,
      padding: `${fontSize * 0.35}px ${fontSize * 0.6}px`,
      border: `${Math.max(2, fontSize * 0.08)}px solid ${brand.colors.white}`,
      background: "rgba(12,8,18,0.72)",
      ...roleStyle(textRoles.meta, fontSize),
      color: brand.colors.white,
    }}
  >
    DEMO · NOTICIA FICTICIA
  </div>
);

/** Grano fotografico sutil y vivo (posicion deterministica por frame). */
export const Grain: React.FC<{ opacity?: number }> = ({ opacity = 0.07 }) => {
  const frame = useCurrentFrame();
  const x = (frame * 137) % 256;
  const y = (frame * 241) % 256;
  return (
    <AbsoluteFill
      style={{
        backgroundImage: `url(${staticFile("textures/grain.png")})`,
        backgroundSize: "256px 256px",
        backgroundPosition: `${x}px ${y}px`,
        mixBlendMode: "overlay",
        opacity,
        pointerEvents: "none",
      }}
    />
  );
};

/** Velo funcional de legibilidad (no decorativo): oscurece donde va texto. */
export const Scrim: React.FC<{ from: "bottom" | "top"; size: number; strength?: number; color?: string }> = ({
  from,
  size,
  strength = 0.86,
  color = "12,8,18",
}) => (
  <div
    style={{
      position: "absolute",
      left: 0,
      right: 0,
      [from]: 0,
      height: size,
      background: `linear-gradient(to ${from === "bottom" ? "top" : "bottom"}, rgba(${color},${strength}) 0%, rgba(${color},${strength * 0.72}) 38%, rgba(${color},0) 100%)`,
    }}
  />
);
