import React, { useMemo } from "react";
import { AbsoluteFill, useVideoConfig } from "remotion";
import { brand } from "../brand/brand.config";
import { getCategory } from "../brand/categories";
import { BrandLogo, DemoBadge, Grain, MetaLine } from "../components/brand";
import { FontGate } from "../components/FontGate";
import { framingFor, PhotoLayer, WindowedPhoto } from "../components/media";
import { getLayout, type Layout } from "../design/layout";
import { fitTextBlock, layoutParagraph, measure, stripEmphasis, type TextBlockLayout } from "../design/textLayout";
import { roleStyle, textRoles, upper, type TextRole } from "../design/tokens";
import { parallelogram, slashCorner, slashRun } from "../engine/animations/geometry";
import { TextReveal } from "../engine/animations/TextReveal";
import type { Content, Presentation } from "../schema/piece";
import type { TemplateProps } from "./shared";

/**
 * D · STATIC EDITORIAL POST. Pieza grafica, no un fotograma de video. Variantes:
 * - hero: foto a sangre, titular sobre velo inferior (titulos cortos/medios).
 * - split: foto arriba, panel solido abajo con corte diagonal (titulos largos o
 *   fotos apaisadas).
 * - type: afiche tipografico sin foto (urgencias o notas sin imagen).
 * Ademas, slides de carrusel: foto secundaria y texto.
 */

export type StaticVariant = "hero" | "split" | "type";

/** Eleccion automatica segun foto disponible, formato y largo del titular. */
export const chooseStaticVariant = (content: Content, presentation: Presentation, layout: Layout): StaticVariant => {
  if (presentation.staticVariant !== "auto") {
    if (presentation.staticVariant !== "type" && content.photos.length === 0) return "type";
    return presentation.staticVariant;
  }
  const photo = content.photos[0];
  if (!photo) return "type";
  const chars = stripEmphasis(content.headline).length;
  const longLimit = layout.format === "square" ? 62 : layout.format === "portrait" ? 78 : 96;
  if (chars > longLimit) return "split";
  // Foto muy apaisada para el formato: mejor arriba entera que recortada.
  if (photo.width && photo.height && photo.width / photo.height > 1.25 && layout.format !== "reel") return "split";
  return "hero";
};

const StaticInner: React.FC<TemplateProps> = ({ piece }) => {
  const { content, presentation } = piece;
  const { width, height } = useVideoConfig();
  const layout = getLayout(presentation.format, width, height);
  const accent = presentation.accent || (content.breaking ? brand.colors.accent : getCategory(content.category).accent);
  const slide = presentation.slide;

  let body: React.ReactNode;
  if (slide && slide.kind === "photo") body = <PhotoSlide content={content} layout={layout} index={slide.index} total={slide.total} />;
  else if (slide && slide.kind === "text") body = <TextSlide content={content} layout={layout} text={slide.text ?? ""} index={slide.index} total={slide.total} accent={accent} />;
  else {
    const variant = chooseStaticVariant(content, presentation, layout);
    const total = slide?.total ?? 1;
    body =
      variant === "hero" ? (
        <HeroPost content={content} layout={layout} accent={accent} total={total} />
      ) : variant === "split" ? (
        <SplitPost content={content} layout={layout} accent={accent} total={total} />
      ) : (
        <TypePost content={content} layout={layout} accent={accent} total={total} />
      );
  }
  return (
    <AbsoluteFill style={{ background: brand.colors.ink, overflow: "hidden" }}>
      {body}
      {content.isDemo ? <DemoBadge fontSize={Math.round(18 * layout.u)} top={Math.round(26 * layout.u)} right={Math.round(26 * layout.u)} /> : null}
    </AbsoluteFill>
  );
};

// ---------- piezas comunes ----------

const Headline: React.FC<{ block: TextBlockLayout; role: TextRole; color: string; accent: string; markerText?: string; emphasis?: "marker" | "color" | "italic" }> = ({
  block,
  role,
  color,
  accent,
  markerText,
  emphasis = "marker",
}) => <TextReveal layout={block} role={role} color={color} accent={accent} mode="none" emphasisStyle={emphasis} markerTextColor={markerText ?? brand.colors.ink} />;

/** Etiqueta de categoria estatica (paralelogramo). */
const Tag: React.FC<{ label: string; accent: string; fontSize: number; textColor?: string }> = ({ label, accent, fontSize, textColor = brand.colors.ink }) => {
  const h = fontSize * 1.9;
  const run = slashRun(h);
  const text = upper(label);
  const w = Math.round(measure(text, textRoles.kicker, fontSize) + run * 2 + fontSize * 1.0);
  return (
    <div style={{ position: "relative", width: w, height: h }}>
      <div style={{ position: "absolute", inset: 0, background: accent, clipPath: parallelogram(w, h) }} />
      <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", paddingLeft: run + fontSize * 0.5 }}>
        <span style={{ ...roleStyle(textRoles.kicker, fontSize), color: textColor }}>{text}</span>
      </div>
    </div>
  );
};

const LocationLine: React.FC<{ text?: string; fontSize: number; color: string; pin: string }> = ({ text, fontSize, color, pin }) =>
  text ? (
    <div style={{ display: "flex", alignItems: "center", gap: fontSize * 0.45 }}>
      <svg width={fontSize * 0.8} height={fontSize * 1.05} viewBox="0 0 19 25">
        <path d="M9.5 0C4.25 0 0 4.2 0 9.4 0 16.4 9.5 25 9.5 25S19 16.4 19 9.4C19 4.2 14.75 0 9.5 0Z" fill={pin} />
        <circle cx="9.5" cy="9.4" r="3.6" fill="rgba(0,0,0,0.55)" />
      </svg>
      <span style={{ ...roleStyle(textRoles.meta, fontSize), color }}>{upper(text)}</span>
    </div>
  ) : null;

const SwipeHint: React.FC<{ layout: Layout; color: string; total: number }> = ({ layout, color, total }) =>
  total > 1 ? (
    <div style={{ display: "flex", alignItems: "center", gap: 12 * layout.u, ...roleStyle(textRoles.meta, layout.type.meta), color }}>
      <span>{upper(brand.copy.swipeHint)}</span>
      <svg width={44 * layout.u} height={18 * layout.u} viewBox="0 0 44 18">
        <path d="M0 9h38M30 1l9 8-9 8" stroke={color} strokeWidth="3" fill="none" />
      </svg>
    </div>
  ) : null;

const useHeadline = (content: Content, layout: Layout, role: TextRole, widthFactor: number, maxHeightFactor: number, scale = 1) =>
  useMemo(
    () =>
      fitTextBlock({
        text: content.headline,
        role,
        maxWidth: layout.contentWidth * widthFactor,
        maxLines: layout.type.headlineLines,
        preferLines: layout.type.headlinePrefer,
        minSize: Math.round(layout.type.headlineMin * scale),
        maxSize: Math.round(layout.type.headlineMax * scale),
        maxHeight: layout.height * maxHeightFactor,
        emphasisItalic: role === textRoles.editorialHeadline,
      }),
    [content.headline, layout, role, widthFactor, maxHeightFactor, scale],
  );

// ---------- variantes ----------

const HeroPost: React.FC<{ content: Content; layout: Layout; accent: string; total: number }> = ({ content, layout, accent, total }) => {
  const photo = content.photos[0];
  const u = layout.u;
  const block = useHeadline(content, layout, textRoles.postHeadline, 1, layout.format === "square" ? 0.34 : 0.36);
  const framing = framingFor(photo, layout.width, layout.height);
  const bottom = layout.format === "reel" ? layout.safeBottom : Math.round(72 * u);
  return (
    <AbsoluteFill>
      {framing === "cover" ? <PhotoLayer photo={photo} /> : <WindowedPhoto photo={photo} top={layout.height * 0.08} height={(layout.width * (photo.height ?? 1)) / (photo.width ?? 1)} />}
      {/* Velos funcionales: arriba para la firma, abajo para el titular */}
      <AbsoluteFill style={{ background: "linear-gradient(to bottom, rgba(12,8,18,0.55) 0%, rgba(12,8,18,0) 22%)" }} />
      <AbsoluteFill
        style={{
          background: `linear-gradient(to top, rgba(12,8,18,0.96) 0%, rgba(12,8,18,0.9) ${Math.round(((block.height + 260 * u) / layout.height) * 60)}%, rgba(12,8,18,0) ${Math.round(((block.height + 420 * u) / layout.height) * 100)}%)`,
        }}
      />
      <Grain opacity={0.05} />
      <div style={{ position: "absolute", left: layout.margin, top: layout.format === "reel" ? layout.safeTop : Math.round(58 * u) }}>
        <BrandLogo height={Math.round(50 * u)} />
      </div>
      <div style={{ position: "absolute", left: layout.margin, right: layout.margin, bottom, display: "flex", flexDirection: "column", gap: 24 * u }}>
        <div style={{ display: "flex", alignItems: "center", gap: 24 * u }}>
          <Tag label={content.breaking ? brand.copy.breakingLabel : getCategory(content.category).label} accent={content.breaking ? brand.colors.signal : accent} textColor={content.breaking ? brand.colors.white : brand.colors.ink} fontSize={layout.type.kicker * 0.9} />
          <LocationLine text={content.location} fontSize={layout.type.meta} color={brand.colors.white} pin={accent} />
        </div>
        <Headline block={block} role={textRoles.postHeadline} color={brand.colors.white} accent={accent} />
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 6 * u }}>
          <MetaLine date={content.date} source={content.source.name} fontSize={layout.type.meta} color="rgba(255,255,255,0.78)" separatorColor={accent} />
          <SwipeHint layout={layout} color={brand.colors.white} total={total} />
        </div>
      </div>
    </AbsoluteFill>
  );
};

const SplitPost: React.FC<{ content: Content; layout: Layout; accent: string; total: number }> = ({ content, layout, accent, total }) => {
  const photo = content.photos[0];
  const u = layout.u;
  const block = useHeadline(content, layout, textRoles.postHeadline, 1, layout.format === "square" ? 0.3 : 0.32, 0.86);
  const bottomPad = layout.format === "reel" ? layout.safeBottom : Math.round(64 * u);
  const panelContent = block.height + layout.type.kicker * 1.9 + 28 * u + layout.type.meta * 1.4 + 34 * u;
  // Respiro superior corto: la categoria arranca cerca del borde del panel.
  const panelH = Math.round(panelContent + bottomPad + 22 * u);
  const photoH = layout.height - panelH + Math.round(60 * u);
  const cutH = Math.round(60 * u);
  return (
    <AbsoluteFill style={{ background: brand.colors.primary }}>
      <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: photoH, overflow: "hidden" }}>
        <PhotoLayer photo={photo} />
        <AbsoluteFill style={{ background: "linear-gradient(to bottom, rgba(12,8,18,0.5) 0%, rgba(12,8,18,0) 26%)" }} />
      </div>
      {/* Panel con corte diagonal en la pendiente de la marca */}
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: layout.height - panelH - cutH,
          height: panelH + cutH,
          background: brand.colors.primary,
          clipPath: `polygon(0px ${cutH}px, ${layout.width * 0.62}px ${cutH}px, ${layout.width * 0.62 + slashRun(cutH)}px 0px, ${layout.width}px 0px, ${layout.width}px ${panelH + cutH}px, 0px ${panelH + cutH}px)`,
        }}
      />
      <div style={{ position: "absolute", right: 0, top: layout.height - panelH - cutH, width: layout.width * 0.38 - slashRun(cutH) + 2, height: Math.max(6, 10 * u), background: accent }} />
      <AbsoluteFill style={{ background: brand.colors.accent, clipPath: slashCorner(1, layout.width, layout.height, "bottom-right", 0.12) }} />
      <Grain opacity={0.05} />
      <div style={{ position: "absolute", left: layout.margin, top: layout.format === "reel" ? layout.safeTop : Math.round(58 * u) }}>
        <BrandLogo height={Math.round(50 * u)} />
      </div>
      <div style={{ position: "absolute", left: layout.margin, right: layout.margin, bottom: bottomPad, display: "flex", flexDirection: "column", gap: 28 * u }}>
        <div style={{ display: "flex", alignItems: "center", gap: 24 * u }}>
          <Tag label={content.breaking ? brand.copy.breakingLabel : getCategory(content.category).label} accent={content.breaking ? brand.colors.signal : accent} textColor={content.breaking ? brand.colors.white : brand.colors.ink} fontSize={layout.type.kicker * 0.9} />
          <LocationLine text={content.location} fontSize={layout.type.meta} color={brand.colors.white} pin={accent} />
        </div>
        <Headline block={block} role={textRoles.postHeadline} color={brand.colors.white} accent={accent} />
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <MetaLine date={content.date} source={content.source.name} fontSize={layout.type.meta} color="rgba(255,255,255,0.78)" separatorColor={accent} />
          <SwipeHint layout={layout} color={brand.colors.white} total={total} />
        </div>
      </div>
    </AbsoluteFill>
  );
};

const TypePost: React.FC<{ content: Content; layout: Layout; accent: string; total: number }> = ({ content, layout, total }) => {
  const u = layout.u;
  const urgent = content.breaking;
  const field = urgent ? brand.colors.accent : brand.colors.primary;
  const ink = urgent ? brand.colors.ink : brand.colors.white;
  const corner = urgent ? brand.colors.primary : brand.colors.accent;
  const block = useHeadline(content, layout, { ...textRoles.breakingHeadline, lineHeight: 0.98 }, 1, 0.5, 1.12);
  return (
    <AbsoluteFill style={{ background: field }}>
      <AbsoluteFill style={{ background: corner, clipPath: slashCorner(1, layout.width, layout.height, "top-left", 0.22) }} />
      <AbsoluteFill style={{ background: corner, clipPath: slashCorner(1, layout.width, layout.height, "bottom-right", 0.26) }} />
      <Grain opacity={0.06} />
      <div style={{ position: "absolute", left: layout.margin, top: layout.format === "reel" ? layout.safeTop : Math.round(58 * u) }}>
        {urgent ? (
          <div style={{ background: brand.colors.primary, padding: `${10 * u}px ${18 * u}px` }}>
            <BrandLogo height={Math.round(46 * u)} />
          </div>
        ) : (
          <BrandLogo height={Math.round(50 * u)} />
        )}
      </div>
      <div style={{ position: "absolute", left: layout.margin, right: layout.margin, top: "50%", translate: "0 -50%", display: "flex", flexDirection: "column", gap: 30 * u }}>
        <div style={{ display: "flex", alignItems: "center", gap: 18 * u }}>
          {urgent ? <div style={{ width: 22 * u, height: 22 * u, borderRadius: "50%", background: brand.colors.signal }} /> : null}
          <span style={{ ...roleStyle(textRoles.kicker, layout.type.kicker), color: ink }}>
            {upper(urgent ? brand.copy.breakingLabel : getCategory(content.category).label)}
          </span>
        </div>
        <Headline block={block} role={{ ...textRoles.breakingHeadline, lineHeight: 0.98 }} color={ink} accent={urgent ? brand.colors.primary : brand.colors.accent} markerText={urgent ? brand.colors.white : brand.colors.ink} />
        <div style={{ height: Math.max(4, 6 * u), width: 120 * u, background: ink }} />
        <LocationLine text={content.location} fontSize={layout.type.meta} color={ink} pin={ink} />
        <MetaLine date={content.date} source={content.source.name} fontSize={layout.type.meta} color={ink} />
      </div>
      <div style={{ position: "absolute", left: layout.margin, bottom: layout.format === "reel" ? layout.safeBottom : Math.round(64 * u) }}>
        <SwipeHint layout={layout} color={ink} total={total} />
      </div>
    </AbsoluteFill>
  );
};

// ---------- slides de carrusel ----------

const SlideCounter: React.FC<{ layout: Layout; index: number; total: number; color: string }> = ({ layout, index, total, color }) => (
  <span style={{ ...roleStyle(textRoles.meta, layout.type.meta), color }}>
    {String(index + 1).padStart(2, "0")} / {String(total).padStart(2, "0")}
  </span>
);

const PhotoSlide: React.FC<{ content: Content; layout: Layout; index: number; total: number }> = ({ content, layout, index, total }) => {
  const photo = content.photos[Math.min(index, content.photos.length - 1)] ?? content.photos[0];
  const u = layout.u;
  if (!photo) return null;
  const framing = framingFor(photo, layout.width, layout.height);
  return (
    <AbsoluteFill>
      {framing === "cover" ? <PhotoLayer photo={photo} /> : <WindowedPhoto photo={photo} top={(layout.height - (layout.width * (photo.height ?? 1)) / (photo.width ?? 1)) / 2} height={(layout.width * (photo.height ?? 1)) / (photo.width ?? 1)} />}
      <AbsoluteFill style={{ background: "linear-gradient(to top, rgba(12,8,18,0.7) 0%, rgba(12,8,18,0) 24%)" }} />
      <div style={{ position: "absolute", left: layout.margin, right: layout.margin, bottom: Math.round(56 * u), display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <BrandLogo variant="mark" height={Math.round(54 * u)} />
        <div style={{ display: "flex", gap: 22 * u, alignItems: "center" }}>
          {photo.credit ? <span style={{ ...roleStyle(textRoles.meta, layout.type.meta * 0.9), color: "rgba(255,255,255,0.75)" }}>{upper(photo.credit)}</span> : null}
          <SlideCounter layout={layout} index={index} total={total} color={brand.colors.white} />
        </div>
      </div>
    </AbsoluteFill>
  );
};

/**
 * Slide de texto del carrusel, con el lenguaje de P5: campo violeta, esquinas
 * ambar, titular condensado como recordatorio y el parrafo de contexto.
 */
const TextSlide: React.FC<{ content: Content; layout: Layout; text: string; index: number; total: number; accent: string }> = ({ content, layout, text, index, total }) => {
  const u = layout.u;
  const width = layout.contentWidth;
  const textWidth = width - Math.round(40 * u);
  const titleRole = { ...textRoles.breakingHeadline, lineHeight: 0.98 };
  const title = useMemo(
    () =>
      fitTextBlock({
        text: content.headline,
        role: titleRole,
        maxWidth: width,
        maxLines: 3,
        preferLines: 2,
        minSize: Math.round(48 * u),
        maxSize: Math.round(76 * u),
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [content.headline, width, u],
  );
  const para = useMemo(() => {
    // Cuerpo que entra en el alto que deja el titular (de 50 a 34 px a 1080).
    const maxH = layout.height - 470 * u - title.height;
    for (let size = Math.round(50 * u); size >= Math.round(34 * u); size -= 2) {
      const l = layoutParagraph(text, textRoles.deck, size, textWidth);
      if (l.height <= maxH) return l;
    }
    return layoutParagraph(text, textRoles.deck, Math.round(34 * u), textWidth);
  }, [text, layout, u, textWidth, title.height]);
  const last = index >= total - 1;
  return (
    <AbsoluteFill style={{ background: brand.colors.primary }}>
      <AbsoluteFill style={{ background: brand.colors.accent, clipPath: slashCorner(1, layout.width, layout.height, "top-left", 0.16) }} />
      <AbsoluteFill style={{ background: brand.colors.accent, clipPath: slashCorner(1, layout.width, layout.height, "bottom-right", 0.2) }} />
      <Grain opacity={0.06} />
      <div style={{ position: "absolute", left: layout.margin, top: Math.round(58 * u) }}>
        <BrandLogo height={Math.round(50 * u)} />
      </div>
      <div style={{ position: "absolute", left: layout.margin, right: layout.margin, top: "50%", translate: "0 -50%", display: "flex", flexDirection: "column", gap: 30 * u }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ ...roleStyle(textRoles.kicker, layout.type.kicker), color: brand.colors.accent }}>{upper(getCategory(content.category).label)}</span>
          <SlideCounter layout={layout} index={index} total={total} color="rgba(255,255,255,0.8)" />
        </div>
        <Headline block={title} role={titleRole} color={brand.colors.white} accent={brand.colors.accent} markerText={brand.colors.ink} />
        <div style={{ height: Math.max(4, 6 * u), width: 120 * u, background: brand.colors.accent }} />
        <div style={{ display: "flex", gap: 32 * u }}>
          <div style={{ width: Math.round(8 * u), background: "rgba(255,255,255,0.22)", flexShrink: 0 }} />
          <TextReveal layout={para} role={textRoles.deck} color={brand.colors.white} accent={brand.colors.accent} mode="none" />
        </div>
        <MetaLine date={content.date} source={content.source.name} fontSize={layout.type.meta} color="rgba(255,255,255,0.78)" separatorColor={brand.colors.accent} />
      </div>
      {!last ? (
        <div style={{ position: "absolute", left: layout.margin, bottom: Math.round(64 * u) }}>
          <SwipeHint layout={layout} color={brand.colors.white} total={total} />
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

export const StaticPost: React.FC<TemplateProps> = ({ piece }) => (
  <FontGate>
    <StaticInner piece={piece} />
  </FontGate>
);
