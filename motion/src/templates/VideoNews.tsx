import React, { useMemo } from "react";
import { Audio } from "@remotion/media";
import { AbsoluteFill, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { brand } from "../brand/brand.config";
import { getCategory } from "../brand/categories";
import { BrandLogo, BreakingLabel, CategoryTag, Grain, MetaLine } from "../components/brand";
import { resolveSrc, VideoLayer } from "../components/media";
import { FontGate } from "../components/FontGate";
import { fitTextBlock, layoutParagraph, stripEmphasis } from "../design/textLayout";
import { roleStyle, textRoles, upper } from "../design/tokens";
import { LocationTag } from "../engine/animations/editorial";
import { slashCorner } from "../engine/animations/geometry";
import { GrowBar, Rise } from "../engine/animations/primitives";
import { TextReveal } from "../engine/animations/TextReveal";
import { AnimationContext, DEFAULT_ANIMATION, ramp, sec } from "../engine/timing";
import type { Content } from "../schema/piece";
import { EndCard, OUTRO_SECONDS, type TemplateProps } from "./shared";
import { getLayout } from "../design/layout";

/**
 * E · VIDEO NEWS (reels de video real). El video es el protagonista y el texto
 * esta SIEMPRE en pantalla:
 * - titular fijo arriba (entra palabra por palabra en el primer segundo);
 * - video completo en el centro, sin fondo desenfocado: campo de marca solido;
 * - "Que se sabe" abajo: puntos cortos que rotan durante todo el video.
 * Todo lo importante vive entre y=300 y y=1620 (recorte 4:5 del feed y zona
 * util del reel). Videos verticales: a pantalla completa con velos de lectura.
 */

const FEED_TOP = 300;
const FEED_BOTTOM = 1620;

type Geometry = { mode: "boxed" | "full"; top: number; height: number; width: number; left: number };

const videoGeometry = (content: Content, W: number, u: number): Geometry => {
  const clip = content.videos[0];
  const aspect = clip?.width && clip?.height ? clip.width / clip.height : 16 / 9;
  if (aspect < 0.9) return { mode: "full", top: 0, height: 1920 * u, width: W, left: 0 };
  const maxH = 700 * u;
  const height = Math.min(W / aspect, maxH);
  const width = height * aspect;
  const top = Math.round(690 * u + (maxH - height) * 0.35);
  return { mode: "boxed", top, height: Math.round(height), width: Math.round(width), left: Math.round((W - width) / 2) };
};

/** Puntos de "Que se sabe": las claves sinteticas; si no hay, oraciones cortas de la bajada. */
export const knownPoints = (content: Content): string[] => {
  const points = content.highlights.map((h) => h.trim()).filter(Boolean);
  if (points.length) return points.slice(0, 4);
  return stripEmphasis(content.deck)
    .split(/(?<=[.!?])\s+/)
    .map((s) => s.trim().replace(/[.]$/, ""))
    .filter((s) => s.length >= 12 && s.length <= 110)
    .slice(0, 3);
};

const VideoInner: React.FC<TemplateProps> = ({ piece }) => {
  const { content, presentation } = piece;
  const frame = useCurrentFrame();
  const { fps, width: W, height: H, durationInFrames } = useVideoConfig();
  const layout = getLayout("reel", W, H);
  const u = layout.u;
  const margin = Math.round(64 * u);
  const accent = presentation.accent || (content.breaking ? brand.colors.signal : getCategory(content.category).accent);
  const geo = videoGeometry(content, W, u);
  const outroStart = durationInFrames - sec(OUTRO_SECONDS, fps);
  const clip = content.videos[0];

  const headlineTop = Math.round((FEED_TOP + 78) * u);
  const headlineMaxH = geo.mode === "boxed" ? geo.top - headlineTop - 34 * u : 330 * u;
  const headline = useMemo(
    () =>
      fitTextBlock({
        text: content.headline,
        role: textRoles.postHeadline,
        maxWidth: W - margin * 2,
        maxLines: 4,
        preferLines: 3,
        minSize: Math.round(52 * u),
        maxSize: Math.round(92 * u),
        maxHeight: headlineMaxH,
      }),
    [content.headline, W, margin, u, headlineMaxH],
  );

  const points = knownPoints(content);
  const cardTop = geo.mode === "boxed" ? geo.top + geo.height + 40 * u : 1250 * u;
  const cardWidth = W - margin - 150 * u;

  // Rotacion de puntos: cada uno 4.5-7 s, en ciclo hasta el cierre.
  const listStart = sec(1.3, fps);
  const span = Math.max(1, outroStart - listStart);
  const slot = points.length ? Math.max(sec(4.5, fps), Math.min(sec(7, fps), Math.floor(span / points.length))) : span;
  const slots = points.length ? Math.ceil(span / slot) : 0;

  const videoProgress = Math.min(1, frame / Math.max(1, outroStart));
  const intro = ramp(frame, 0, sec(0.5, fps), "snap");

  return (
    <AbsoluteFill style={{ background: brand.colors.primaryDeep }}>
      {/* Campo de marca: degradado violeta y diagonales ambar fuera de la zona util */}
      <AbsoluteFill style={{ background: `radial-gradient(120% 70% at 50% 45%, ${brand.colors.primary} 0%, ${brand.colors.primaryDeep} 70%)` }} />
      <AbsoluteFill style={{ background: brand.colors.accent, clipPath: slashCorner(intro, W, H, "top-left", 0.13), opacity: 0.95 }} />
      <AbsoluteFill style={{ background: brand.colors.accent, clipPath: slashCorner(intro, W, H, "bottom-right", 0.1), opacity: 0.95 }} />

      {clip ? (
        geo.mode === "full" ? (
          <AbsoluteFill>
            <VideoLayer clip={clip} fit="cover" />
            <AbsoluteFill style={{ background: "linear-gradient(to bottom, rgba(12,8,18,0.88) 0%, rgba(12,8,18,0.7) 30%, rgba(12,8,18,0) 46%, rgba(12,8,18,0) 60%, rgba(12,8,18,0.86) 78%, rgba(12,8,18,0.92) 100%)" }} />
          </AbsoluteFill>
        ) : (
          <div style={{ position: "absolute", left: geo.left, top: geo.top, width: geo.width, height: geo.height, overflow: "hidden", boxShadow: "0 30px 80px rgba(0,0,0,0.45)" }}>
            <VideoLayer clip={clip} fit="cover" />
          </div>
        )
      ) : null}
      {clip && geo.mode === "boxed" ? (
        // Barra de avance del video, pegada al borde inferior del cuadro.
        <div style={{ position: "absolute", left: geo.left, top: geo.top + geo.height, width: geo.width, height: Math.max(4, 7 * u), background: "rgba(255,255,255,0.16)" }}>
          <div style={{ width: `${videoProgress * 100}%`, height: "100%", background: accent }} />
        </div>
      ) : null}
      {presentation.audio ? <Audio src={resolveSrc(presentation.audio.src)} volume={presentation.audio.volume} /> : null}
      <Grain opacity={0.05} />

      {/* Fila superior: logo + etiqueta + lugar */}
      <div style={{ position: "absolute", left: margin, right: margin, top: FEED_TOP * u, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <Rise delay={0.05} distance={10}>
          <BrandLogo height={Math.round(46 * u)} />
        </Rise>
        <div style={{ display: "flex", alignItems: "center", gap: 18 * u }}>
          {content.location ? <LocationTag text={content.location} fontSize={layout.type.meta} color={brand.colors.white} pinColor={brand.colors.accent} delay={0.5} /> : null}
          {content.breaking ? (
            <BreakingLabel fontSize={Math.round(layout.type.kicker * 0.82)} delay={0.1} />
          ) : (
            <CategoryTag label={getCategory(content.category).label} accent={accent} fontSize={Math.round(layout.type.kicker * 0.82)} delay={0.1} />
          )}
        </div>
      </div>

      {/* Titular fijo */}
      <div style={{ position: "absolute", left: margin, width: W - margin * 2, top: headlineTop }}>
        <TextReveal
          layout={headline}
          role={textRoles.postHeadline}
          color={brand.colors.white}
          accent={brand.colors.accent}
          emphasisStyle="marker"
          markerTextColor={brand.colors.ink}
          mode="word"
          stagger={0.04}
          duration={0.5}
          delay={0.12}
        />
      </div>

      {/* Que se sabe */}
      {points.length ? (
        <div style={{ position: "absolute", left: margin, top: cardTop, width: cardWidth }}>
          <Rise delay={1.0} distance={14}>
            <div style={{ display: "flex", alignItems: "center", gap: 16 * u, marginBottom: 18 * u }}>
              <GrowBar length={42 * u} thickness={Math.max(3, 6 * u)} color={brand.colors.accent} delay={1.0} />
              <span style={{ ...roleStyle(textRoles.kicker, layout.type.kicker * 0.86), color: brand.colors.accent }}>{upper("Qué se sabe")}</span>
              {points.length > 1 ? <PointDots count={points.length} active={frame < listStart ? 0 : Math.floor((frame - listStart) / slot) % points.length} u={u} /> : null}
            </div>
          </Rise>
          <div style={{ position: "relative", height: 230 * u }}>
            {Array.from({ length: slots }, (_, i) => (
              <Sequence key={i} from={listStart + i * slot} durationInFrames={Math.min(slot, outroStart - (listStart + i * slot))} layout="none">
                <PointText text={points[i % points.length]} width={cardWidth} u={u} last={listStart + (i + 1) * slot >= outroStart} slot={slot} />
              </Sequence>
            ))}
          </div>
        </div>
      ) : null}

      {/* Zocalo: fecha y fuente */}
      <div style={{ position: "absolute", left: margin, right: margin, top: FEED_BOTTOM * u, display: "flex", alignItems: "center" }}>
        <Rise delay={0.8} distance={8}>
          <MetaLine date={content.date} source={content.source.name} fontSize={Math.round(layout.type.meta * 0.9)} color="rgba(255,255,255,0.8)" separatorColor={brand.colors.accent} />
        </Rise>
      </div>

      <Sequence from={outroStart} durationInFrames={durationInFrames - outroStart} name="Cierre">
        <EndCard content={content} layout={layout} accent={accent} />
      </Sequence>
    </AbsoluteFill>
  );
};

const PointDots: React.FC<{ count: number; active: number; u: number }> = ({ count, active, u }) => (
  <div style={{ display: "flex", gap: 8 * u, marginLeft: 8 * u }}>
    {Array.from({ length: count }, (_, i) => (
      <div key={i} style={{ width: (i === active ? 26 : 10) * u, height: 10 * u, borderRadius: 5 * u, background: i === active ? brand.colors.white : "rgba(255,255,255,0.35)" }} />
    ))}
  </div>
);

const PointText: React.FC<{ text: string; width: number; u: number; last: boolean; slot: number }> = ({ text, width, u, last, slot }) => {
  const { fps } = useVideoConfig();
  const para = useMemo(() => {
    for (let size = Math.round(60 * u); size >= Math.round(40 * u); size -= 2) {
      const l = layoutParagraph(text, textRoles.deckStrong, size, width);
      if (l.lines.length <= 3) return l;
    }
    return layoutParagraph(text, textRoles.deckStrong, Math.round(40 * u), width);
  }, [text, width, u]);
  return (
    <div style={{ position: "absolute", left: 0, top: 0, width }}>
      <TextReveal
        layout={para}
        role={textRoles.deckStrong}
        color={brand.colors.white}
        accent={brand.colors.accent}
        mode="line"
        stagger={0.07}
        duration={0.5}
        delay={0.05}
        exitAt={last ? undefined : slot - sec(0.35, fps)}
      />
    </div>
  );
};

export const VideoNews: React.FC<TemplateProps> = ({ piece }) => (
  <FontGate>
    <AnimationContext.Provider value={{ ...DEFAULT_ANIMATION, ...piece.presentation.animation }}>
      <VideoInner piece={piece} />
    </AnimationContext.Provider>
  </FontGate>
);
