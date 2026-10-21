import React, { useMemo } from "react";
import { AbsoluteFill, useVideoConfig } from "remotion";
import { brand } from "../brand/brand.config";
import { getCategory } from "../brand/categories";
import { BrandLogo, Grain, MetaLine } from "../components/brand";
import { FontGate } from "../components/FontGate";
import { PhotoLayer } from "../components/media";
import { getLayout } from "../design/layout";
import { fitTextBlock, measure } from "../design/textLayout";
import { roleStyle, textRoles, upper } from "../design/tokens";
import { parallelogram, slashCorner, slashRun } from "../engine/animations/geometry";
import { TextReveal } from "../engine/animations/TextReveal";
import type { TemplateProps } from "./shared";

/**
 * F · PORTADA DE VIDEO (still 1080x1920). Sirve a la vez como portada del reel
 * (9:16) y como miniatura del feed y la grilla: todo lo que informa (foto,
 * etiqueta, titular, boton de play) vive dentro del recorte central 4:5
 * (y=285..1635); arriba y abajo solo hay campo de marca.
 * Foto: un cuadro del propio video (`content.photos[0]`).
 */
const SAFE_TOP = 300;
const SAFE_BOTTOM = 1620;

const Tag: React.FC<{ label: string; color: string; textColor: string; fontSize: number }> = ({ label, color, textColor, fontSize }) => {
  const h = fontSize * 1.9;
  const run = slashRun(h);
  const text = upper(label);
  const w = Math.round(measure(text, textRoles.kicker, fontSize) + run * 2 + fontSize);
  return (
    <div style={{ position: "relative", width: w, height: h }}>
      <div style={{ position: "absolute", inset: 0, background: color, clipPath: parallelogram(w, h) }} />
      <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", paddingLeft: run + fontSize * 0.5 }}>
        <span style={{ ...roleStyle(textRoles.kicker, fontSize), color: textColor }}>{text}</span>
      </div>
    </div>
  );
};

const PlayBadge: React.FC<{ size: number }> = ({ size }) => (
  <div style={{ width: size, height: size, borderRadius: "50%", background: "rgba(12,8,18,0.55)", border: `${Math.round(size * 0.05)}px solid ${brand.colors.white}`, display: "flex", alignItems: "center", justifyContent: "center" }}>
    <svg width={size * 0.38} height={size * 0.44} viewBox="0 0 19 22">
      <path d="M0 0 L19 11 L0 22 Z" fill={brand.colors.white} />
    </svg>
  </div>
);

const CoverInner: React.FC<TemplateProps> = ({ piece }) => {
  const { content } = piece;
  const { width: W, height: H } = useVideoConfig();
  const layout = getLayout("reel", W, H);
  const u = layout.u;
  const margin = Math.round(70 * u);
  const photo = content.photos[0];
  const vertical = !!(photo?.width && photo?.height && photo.width / photo.height < 0.9);
  const block = useMemo(
    () =>
      fitTextBlock({
        text: content.headline,
        role: textRoles.postHeadline,
        maxWidth: W - margin * 2,
        maxLines: 4,
        preferLines: 3,
        minSize: Math.round(64 * u),
        maxSize: Math.round(112 * u),
        maxHeight: 440 * u,
      }),
    [content.headline, W, margin, u],
  );
  const tagSize = Math.round(30 * u);
  const metaH = 40 * u;
  const textTop = SAFE_BOTTOM * u - 40 * u - metaH - block.height - 30 * u - tagSize * 1.9 - 26 * u;
  // Foto: desde el borde util superior hasta un poco por debajo del inicio del texto (fundido).
  const photoTop = vertical ? 0 : SAFE_TOP * u - 15 * u;
  const photoBottom = vertical ? H : Math.max(textTop + 160 * u, 1000 * u);
  const isBreaking = content.breaking;
  return (
    <AbsoluteFill style={{ background: brand.colors.primaryDeep }}>
      <AbsoluteFill style={{ background: `radial-gradient(120% 70% at 50% 55%, ${brand.colors.primary} 0%, ${brand.colors.primaryDeep} 72%)` }} />
      {photo ? (
        <div style={{ position: "absolute", left: 0, right: 0, top: photoTop, height: photoBottom - photoTop, overflow: "hidden" }}>
          <PhotoLayer photo={photo} />
          <AbsoluteFill style={{ background: "linear-gradient(to bottom, rgba(30,13,51,0.55) 0%, rgba(30,13,51,0) 22%, rgba(30,13,51,0) 50%, rgba(30,13,51,0.92) 92%, rgba(30,13,51,1) 100%)" }} />
        </div>
      ) : null}
      {vertical ? <AbsoluteFill style={{ background: "linear-gradient(to bottom, rgba(30,13,51,0) 40%, rgba(30,13,51,0.9) 75%, rgba(30,13,51,0.96) 100%)" }} /> : null}
      <AbsoluteFill style={{ background: brand.colors.accent, clipPath: slashCorner(1, W, H, "top-left", 0.13) }} />
      <AbsoluteFill style={{ background: brand.colors.accent, clipPath: slashCorner(1, W, H, "bottom-right", 0.1) }} />
      <Grain opacity={0.05} />

      <div style={{ position: "absolute", left: margin, top: SAFE_TOP * u + 24 * u }}>
        <BrandLogo height={Math.round(52 * u)} />
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, top: (vertical ? 760 * u : (photoTop + Math.min(photoBottom, textTop)) / 2) - 70 * u, display: "flex", justifyContent: "center" }}>
        <PlayBadge size={Math.round(140 * u)} />
      </div>

      <div style={{ position: "absolute", left: margin, right: margin, top: textTop, display: "flex", flexDirection: "column", gap: 26 * u }}>
        <Tag
          label={isBreaking ? brand.copy.breakingLabel : getCategory(content.category).label}
          color={isBreaking ? brand.colors.signal : getCategory(content.category).accent}
          textColor={isBreaking ? brand.colors.white : brand.colors.ink}
          fontSize={tagSize}
        />
        <TextReveal layout={block} role={textRoles.postHeadline} color={brand.colors.white} accent={brand.colors.accent} mode="none" emphasisStyle="marker" markerTextColor={brand.colors.ink} />
        <MetaLine date={content.date} source={content.source.name} fontSize={Math.round(layout.type.meta)} color="rgba(255,255,255,0.8)" separatorColor={brand.colors.accent} />
      </div>
    </AbsoluteFill>
  );
};

export const VideoCover: React.FC<TemplateProps> = ({ piece }) => (
  <FontGate>
    <CoverInner piece={piece} />
  </FontGate>
);
