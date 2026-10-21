import React from "react";
import { AbsoluteFill, Img, useVideoConfig } from "remotion";
import { brand } from "../brand/brand.config";
import { getCategory } from "../brand/categories";
import { Grain } from "../components/brand";
import { resolveSrc, PHOTO_GRADE } from "../components/media";
import { measure } from "../design/textLayout";
import { roleStyle, textRoles, upper, type TextRole } from "../design/tokens";
import { parallelogram, slashCorner, slashRun } from "../engine/animations/geometry";

/**
 * Piezas comunes de los formatos de servicio, resumen e historias. Los datos de
 * cada pieza viajan en `content.extra` (los arma el pipeline desde fuentes
 * oficiales o desde notas ya publicadas: nunca se inventan).
 */

export type Extra = Record<string, unknown> & { kind?: string };

/**
 * `content.extra` con las referencias "photo:N" resueltas a `content.photos[N].src`:
 * las fotos locales viajan en `photos` porque el renderer solo copia esas rutas.
 */
export const extraOf = (content: { extra?: Record<string, unknown>; photos?: { src: string }[] }): Extra => {
  const photos = content.photos ?? [];
  const walk = (v: unknown): unknown => {
    if (typeof v === "string") {
      const m = /^photo:(\d+)$/.exec(v);
      return m ? photos[Number(m[1])]?.src : v;
    }
    if (Array.isArray(v)) return v.map(walk);
    if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, val]) => [k, walk(val)]));
    return v;
  };
  return walk(content.extra ?? {}) as Extra;
};

/** Texto con rol tipografico pero con salto de linea normal (roleStyle trae `pre`). */
export const T: React.FC<{ role: TextRole; size: number; color?: string; style?: React.CSSProperties; children: React.ReactNode; lines?: number }> = ({
  role,
  size,
  color = brand.colors.white,
  style,
  children,
  lines,
}) => (
  <div
    style={{
      ...roleStyle(role, size),
      whiteSpace: "normal",
      textWrap: "balance",
      color,
      textTransform: role.uppercase ? "uppercase" : "none",
      ...(lines ? { display: "-webkit-box", WebkitLineClamp: lines, WebkitBoxOrient: "vertical", overflow: "hidden" } : null),
      ...style,
    }}
  >
    {children}
  </div>
);

/** Fondo de marca: violeta, esquinas ambar y grano. */
export const BrandFrame: React.FC<{ corners?: number; children?: React.ReactNode; tone?: "violet" | "deep" }> = ({ corners = 0.11, children, tone = "violet" }) => {
  const { width: W, height: H } = useVideoConfig();
  return (
    <AbsoluteFill style={{ background: brand.colors.primaryDeep, overflow: "hidden" }}>
      <AbsoluteFill
        style={{
          background:
            tone === "violet"
              ? `radial-gradient(120% 80% at 30% 20%, ${brand.colors.primary} 0%, ${brand.colors.primaryDeep} 75%)`
              : `radial-gradient(110% 70% at 50% 0%, #2a1247 0%, ${brand.colors.primaryDeep} 70%)`,
        }}
      />
      {corners > 0 ? (
        <>
          <AbsoluteFill style={{ background: brand.colors.accent, clipPath: slashCorner(1, W, H, "top-left", corners) }} />
          <AbsoluteFill style={{ background: brand.colors.accent, clipPath: slashCorner(1, W, H, "bottom-right", corners * 0.8) }} />
        </>
      ) : null}
      {children}
      <Grain opacity={0.05} />
    </AbsoluteFill>
  );
};

/** Etiqueta paralelogramo. */
export const Tag: React.FC<{ label: string; color?: string; textColor?: string; size: number }> = ({ label, color = brand.colors.accent, textColor = brand.colors.ink, size }) => {
  const h = size * 1.9;
  const run = slashRun(h);
  const text = upper(label);
  const w = Math.round(measure(text, textRoles.kicker, size) + run * 2 + size);
  return (
    <div style={{ position: "relative", width: w, height: h, flex: "none" }}>
      <div style={{ position: "absolute", inset: 0, background: color, clipPath: parallelogram(w, h) }} />
      <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", paddingLeft: run + size * 0.5 }}>
        <span style={{ ...roleStyle(textRoles.kicker, size), color: textColor }}>{text}</span>
      </div>
    </div>
  );
};

export const CategoryChip: React.FC<{ category?: string; size: number }> = ({ category, size }) => {
  const c = getCategory(category);
  return <Tag label={c.label} color={c.accent} size={size} />;
};

export const Photo: React.FC<{ src?: string; style?: React.CSSProperties; focusY?: number }> = ({ src, style, focusY = 0.4 }) =>
  src ? (
    <Img
      src={resolveSrc(src)}
      style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover", objectPosition: `50% ${focusY * 100}%`, filter: PHOTO_GRADE, ...style }}
    />
  ) : null;

export const fmtNum = (n: number, decimals = 0) =>
  new Intl.NumberFormat("es-AR", { minimumFractionDigits: decimals, maximumFractionDigits: decimals }).format(n);

/** Iconos de clima simples, en linea con la marca (trazos blancos + ambar). */
export const WeatherIcon: React.FC<{ desc: string; size: number }> = ({ desc, size }) => {
  const d = desc.toLowerCase();
  const sun = <circle cx="30" cy="26" r="11" fill={brand.colors.accent} />;
  const cloud = <path d="M18 46h30a10 10 0 0 0 0-20 14 14 0 0 0-27-3 11 11 0 0 0-3 23Z" fill="#fff" />;
  const drops = (
    <g stroke="#6CC9FF" strokeWidth="4" strokeLinecap="round">
      <path d="M22 52l-3 8" />
      <path d="M34 52l-3 8" />
      <path d="M46 52l-3 8" />
    </g>
  );
  const bolt = <path d="M36 48l-8 12h7l-4 10 11-14h-7l4-8Z" fill={brand.colors.accent} />;
  let body: React.ReactNode;
  if (/torment/.test(d)) body = <>{cloud}{bolt}</>;
  else if (/lluv|llovizn|chaparr/.test(d)) body = <>{cloud}{drops}</>;
  else if (/nublado|cubierto|nubos/.test(d)) body = <>{/parcial|algo/.test(d) ? sun : null}{cloud}</>;
  else if (/despejado|soleado|sol/.test(d)) body = sun;
  else body = <>{sun}{cloud}</>;
  return (
    <svg width={size} height={size} viewBox="0 0 70 70">
      {body}
    </svg>
  );
};

/** Cabecera comun: logo + rotulo de seccion + fecha. */
export const SectionHead: React.FC<{ label: string; date?: string; size: number; color?: string }> = ({ label, date, size, color = brand.colors.accent }) => (
  <div style={{ display: "flex", alignItems: "center", gap: size * 0.6, flexWrap: "wrap" }}>
    <Tag label={label} color={color} size={size} />
    {date ? <span style={{ ...roleStyle(textRoles.meta, size * 0.82), color: "rgba(255,255,255,0.78)" }}>{upper(date)}</span> : null}
  </div>
);

export const SourceLine: React.FC<{ text: string; size: number; color?: string }> = ({ text, size, color = "rgba(255,255,255,0.7)" }) => (
  <div style={{ ...roleStyle(textRoles.meta, size), whiteSpace: "normal", color }}>{upper(text)}</div>
);
