import React, { useMemo } from "react";
import { AbsoluteFill, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { brand } from "../brand/brand.config";
import { getCategory } from "../brand/categories";
import { BrandLogo, BreakingLabel, CategoryTag, Grain, MetaLine, Scrim } from "../components/brand";
import { MediaStage } from "../components/MediaStage";
import { fitTextBlock, layoutParagraph } from "../design/textLayout";
import { roleStyle, textRoles, upper } from "../design/tokens";
import { LocationTag } from "../engine/animations/editorial";
import { GrowBar, ImageReveal, Rise } from "../engine/animations/primitives";
import { TextReveal } from "../engine/animations/TextReveal";
import { REVEAL_LEAD } from "../engine/hooks/PhotoHook";
import type { Beat } from "../engine/timeline";
import { ramp, sec, useAnimationConfig } from "../engine/timing";
import { DemoMark, EndCard, HookLayer, NewsStrip, PieceShell, textBottom, type TemplateProps, type TemplateSetup, useTemplateSetup } from "./shared";

/** Alto de la franja de foto: debajo van los textos (los videos siguen a pantalla completa). */
const PHOTO_BAND = 0.58;
/** Desde donde puede empezar la lista "Que se sabe" (solo toca el fundido de la foto). */
const FACTS_TOP = 0.5;

/**
 * A · BREAKING NEWS. Urgencia sin estridencia: etiqueta de ultimo momento desde
 * el frame 0, impacto tipografico, titular condensado gigante sobre la imagen,
 * cortes secos con destello y un cierre de 2 segundos.
 */
const BreakingInner: React.FC<TemplateProps> = ({ piece }) => {
  const setup = useTemplateSetup(piece, "breaking");
  const { content, layout, accent, plan, hook } = setup;
  const { height } = useVideoConfig();
  const holdBeat = plan.beats.find((b) => b.kind === "hold");
  const toplineEnd = holdBeat ? holdBeat.start : plan.outro.start;
  // En el tramo compacto el velo inferior se achica y deja ver el video.
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const fullScrim = height * (layout.format === "reel" ? 0.66 : 0.72);
  const holdP = holdBeat ? ramp(frame, holdBeat.start - sec(0.3, fps), sec(0.6, fps), "glide") : 0;
  const scrimSize = fullScrim - holdP * fullScrim * 0.42;

  const stage = (
    <MediaStage
      content={content}
      plan={plan}
      layout={layout}
      cut="punch"
      accent={accent}
      windowCenter={layout.format === "reel" ? 0.36 : 0.32}
      band={{ top: 0, height: Math.round(height * PHOTO_BAND) }}
      bandBackground={`linear-gradient(to bottom, ${brand.colors.inkSoft}, ${brand.colors.ink})`}
    />
  );

  return (
    <AbsoluteFill>
      {hook.revealsStage ? <ImageReveal duration={0.95} delay={-REVEAL_LEAD}>{stage}</ImageReveal> : stage}
      {/* Tinte de urgencia + velos de legibilidad */}
      <AbsoluteFill style={{ background: "rgba(12,8,18,0.16)" }} />
      <Scrim from="bottom" size={scrimSize} strength={0.94} />
      <Scrim from="top" size={layout.safeTop + 260 * layout.u} strength={0.62} />
      <Grain opacity={0.06} />

      {plan.beats.map((beat, i) => (
        <Sequence key={i} from={beat.start} durationInFrames={beat.duration} name={`Bloque ${beat.kind}`}>
          <BreakingBeat setup={setup} beat={beat} isLast={i === plan.beats.length - 1} />
        </Sequence>
      ))}

      {/* Titular compacto persistente despues del bloque principal */}
      {plan.beats.length > 1 && plan.beats[1].kind !== "hold" ? (
        <Sequence from={plan.beats[1].start} durationInFrames={toplineEnd - plan.beats[1].start} name="Titular compacto">
          <Topline setup={setup} />
        </Sequence>
      ) : null}

      {/* Cromo superior: etiqueta de urgencia y firma */}
      <Sequence durationInFrames={plan.outro.start} name="Cromo">
        <div style={{ position: "absolute", left: layout.margin, top: layout.safeTop }}>
          <BreakingLabel fontSize={layout.type.kicker} delay={0} />
        </div>
        <div style={{ position: "absolute", right: layout.margin, top: layout.safeTop + 4 * layout.u }}>
          <Rise delay={0.2} distance={10}>
            <BrandLogo variant="horizontal" height={Math.round(46 * layout.u)} opacity={0.95} />
          </Rise>
        </div>
      </Sequence>

      <NewsStrip setup={setup} />
      <HookLayer setup={setup} template="breaking" />

      <Sequence from={plan.outro.start} durationInFrames={plan.outro.duration} name="Cierre">
        <EndCard content={content} layout={layout} accent={accent} />
      </Sequence>
      <DemoMark content={content} layout={layout} />
    </AbsoluteFill>
  );
};

/** Ancla inferior comun de los bloques de texto. */
const BottomBlock: React.FC<{ setup: TemplateSetup; children: React.ReactNode }> = ({ setup, children }) => {
  const { layout } = setup;
  return (
    <div
      style={{
        position: "absolute",
        left: layout.margin,
        width: layout.contentWidth,
        bottom: textBottom(layout),
        display: "flex",
        flexDirection: "column",
        gap: 26 * layout.u,
      }}
    >
      {children}
    </div>
  );
};

const BreakingBeat: React.FC<{ setup: TemplateSetup; beat: Beat; isLast: boolean }> = ({ setup, beat, isLast }) => {
  const { content, layout, accent } = setup;
  const { fps, height } = useVideoConfig();
  const cfg = useAnimationConfig();
  const exitAt = isLast || beat.kind === "hold" ? undefined : beat.duration - sec(0.32, fps, cfg.speed);
  // El primer bloque arranca durante la salida del gancho.
  const d0 = beat.kind === "headline" ? 0.05 : 0.12;

  const headline = useMemo(
    () =>
      fitTextBlock({
        text: content.headline,
        role: textRoles.breakingHeadline,
        maxWidth: layout.contentWidth,
        maxLines: layout.type.headlineLines,
        preferLines: layout.type.headlinePrefer,
        minSize: layout.type.headlineMin,
        maxSize: layout.type.headlineMax,
        maxHeight: height * (layout.format === "reel" ? 0.3 : 0.36),
      }),
    [content.headline, layout, height],
  );
  const compact = useMemo(
    () =>
      fitTextBlock({
        text: content.headline,
        role: textRoles.breakingHeadline,
        maxWidth: layout.contentWidth,
        maxLines: 3,
        preferLines: 2,
        minSize: Math.round(48 * layout.u),
        maxSize: Math.round(68 * layout.u),
      }),
    [content.headline, layout],
  );

  if (beat.kind === "hold") {
    return (
      <BottomBlock setup={setup}>
        <TextReveal
          layout={compact}
          role={textRoles.breakingHeadline}
          color={brand.colors.white}
          accent={accent}
          markerTextColor={brand.colors.ink}
          emphasisStyle="marker"
          mode="line"
          stagger={0.06}
          duration={0.5}
          delay={0.2}
        />
        {layout.format !== "reel" ? (
          <Rise delay={0.5} distance={10}>
            <MetaLine date={content.date} source={content.source.name} fontSize={layout.type.meta} color="rgba(255,255,255,0.8)" separatorColor={accent} />
          </Rise>
        ) : null}
      </BottomBlock>
    );
  }

  if (beat.kind === "headline") {
    return (
      <BottomBlock setup={setup}>
        <div style={{ display: "flex", alignItems: "center", gap: 26 * layout.u, flexWrap: "wrap" }}>
          <CategoryTag label={getCategory(content.category).label} accent={accent} fontSize={layout.type.kicker * 0.92} delay={d0} exitAt={exitAt} />
          {content.location ? (
            <LocationTag text={content.location} fontSize={layout.type.meta * 1.05} color={brand.colors.white} pinColor={accent} delay={d0 + 0.18} exitAt={exitAt} />
          ) : null}
        </div>
        <TextReveal
          layout={headline}
          role={textRoles.breakingHeadline}
          color={brand.colors.white}
          accent={accent}
          markerTextColor={brand.colors.ink}
          emphasisStyle="marker"
          mode="line"
          stagger={0.075}
          duration={0.62}
          delay={d0 + 0.1}
          exitAt={exitAt}
        />
        {layout.format !== "reel" ? (
          <Rise delay={d0 + 0.55} distance={14} exitAt={exitAt}>
            <MetaLine date={content.date} source={content.source.name} fontSize={layout.type.meta} color="rgba(255,255,255,0.8)" separatorColor={accent} />
          </Rise>
        ) : null}
      </BottomBlock>
    );
  }

  if (beat.kind === "deck") {
    return <FactsList setup={setup} beat={beat} exitAt={exitAt} />;
  }

  if (beat.kind === "highlight" || beat.kind === "quote") {
    const isQuote = beat.kind === "quote" && content.quote;
    const text = beat.kind === "highlight" ? content.highlights[beat.index] : (content.quote?.text ?? "");
    const role = isQuote ? textRoles.quote : textRoles.deckStrong;
    const size = Math.round((isQuote ? 68 : beat.kind === "highlight" ? 64 : 60) * layout.u);
    const para = layoutParagraph(isQuote ? `“${text}”` : text, role, size, layout.contentWidth - 40 * layout.u);
    const label =
      beat.kind === "highlight" ? `${String(beat.index + 1).padStart(2, "0")} / ${String(content.highlights.length).padStart(2, "0")}` : (content.quote?.author ?? "");
    return (
      <BottomBlock setup={setup}>
        <Rise delay={0.05} distance={12} exitAt={exitAt}>
          <span style={{ ...roleStyle(textRoles.meta, layout.type.meta * 1.1), color: accent }}>{upper(label)}</span>
        </Rise>
        <div style={{ display: "flex", gap: 34 * layout.u, alignItems: "stretch" }}>
          <GrowBar axis="y" length={para.height} thickness={Math.round(10 * layout.u)} color={accent} delay={0.08} duration={0.5} origin="end" />
          <div style={{ flex: 1 }}>
            <TextReveal layout={para} role={role} color={brand.colors.white} accent={accent} mode="line" delay={0.16} stagger={0.07} exitAt={exitAt} />
          </div>
        </div>
      </BottomBlock>
    );
  }
  return null;
};

/**
 * "QUE SE SABE": bajada y claves como lista numerada. Entran de a una y el
 * cuerpo se elige para que la lista entera entre entre el titular compacto de
 * arriba y el zocalo.
 */
const FactsList: React.FC<{ setup: TemplateSetup; beat: Beat; exitAt?: number }> = ({ setup, beat, exitAt }) => {
  const { content, layout, accent } = setup;
  const { fps, height } = useVideoConfig();
  const u = layout.u;
  const items = useMemo(
    () => [beat.withDeck === false ? "" : content.deck, ...content.highlights.slice(0, beat.index)].filter(Boolean),
    [content.deck, content.highlights, beat.index, beat.withDeck],
  );
  const badge = Math.round(56 * u);
  // Mas ancho que el resto de los bloques: solo respeta un borde derecho minimo
  // para no chocar con los iconos de Instagram (que estan mas abajo, a la derecha).
  const listWidth = layout.width - layout.margin - Math.round((layout.format === "reel" ? 96 : 84) * u);
  const indent = badge + Math.round(28 * u);
  const gap = Math.round(34 * u);
  const labelH = layout.type.meta * 1.1 * 1.4 + 26 * u;
  // La lista vive debajo de la foto: entre FACTS_TOP y la base del bloque.
  const top = content.videos.length ? layout.safeTop + layout.type.kicker * 3.1 + 150 * u : height * FACTS_TOP;
  const maxH = height - textBottom(layout) - top - labelH;
  const fitted = useMemo(() => {
    const totalOf = (paras: ReturnType<typeof layoutParagraph>[]) => paras.reduce((acc, p) => acc + Math.max(p.height, badge), 0) + gap * (paras.length - 1);
    // El cuerpo mas grande que entra; si ni al minimo entran todos, se quitan claves del final.
    for (let n = items.length; n >= 1; n--) {
      for (let size = Math.round(66 * u); size >= Math.round(40 * u); size -= 2) {
        const paras = items.slice(0, n).map((t) => layoutParagraph(t, textRoles.deckStrong, size, listWidth - indent));
        if (totalOf(paras) <= maxH) return paras;
      }
    }
    return items.slice(0, 1).map((t) => layoutParagraph(t, textRoles.deckStrong, Math.round(40 * u), listWidth - indent));
  }, [items, u, listWidth, indent, maxH, badge, gap]);
  const beatSeconds = beat.duration / fps;
  const step = Math.min(0.9, (beatSeconds * 0.35) / Math.max(1, fitted.length));
  return (
    <div style={{ position: "absolute", left: layout.margin, width: listWidth, bottom: textBottom(layout), display: "flex", flexDirection: "column", gap: 26 * u }}>
      <Rise delay={0.05} distance={12} exitAt={exitAt}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 * u }}>
          <GrowBar length={44 * u} thickness={Math.max(3, 6 * u)} color={accent} delay={0.05} />
          <span style={{ ...roleStyle(textRoles.meta, layout.type.meta * 1.1), color: accent }}>{upper("Qué se sabe")}</span>
        </div>
      </Rise>
      <div style={{ display: "flex", flexDirection: "column", gap }}>
        {fitted.map((para, i) => {
          const delay = 0.15 + i * step;
          return (
            <div key={i} style={{ display: "flex", gap: indent - badge, alignItems: "flex-start" }}>
              <Rise delay={delay} distance={18} exitAt={exitAt}>
                <div
                  style={{
                    width: badge,
                    height: badge,
                    background: i === 0 ? accent : "rgba(255,255,255,0.12)",
                    border: i === 0 ? "none" : `${Math.max(2, 3 * u)}px solid ${accent}`,
                    boxSizing: "border-box",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    marginTop: Math.max(0, (para.lineHeightPx - badge) / 2),
                    ...roleStyle(textRoles.kicker, Math.round(30 * u)),
                    color: i === 0 ? brand.colors.ink : brand.colors.white,
                  }}
                >
                  {i + 1}
                </div>
              </Rise>
              <div style={{ flex: 1 }}>
                <TextReveal layout={para} role={textRoles.deckStrong} color={brand.colors.white} accent={accent} mode="line" delay={delay + 0.06} stagger={0.06} exitAt={exitAt} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

/** Titular compacto arriba, debajo de la etiqueta, para quien entra tarde. */
const Topline: React.FC<{ setup: TemplateSetup }> = ({ setup }) => {
  const { content, layout } = setup;
  const compact = useMemo(
    () =>
      fitTextBlock({
        text: content.headline.replace(/\*/g, ""),
        role: { ...textRoles.breakingHeadline, lineHeight: 0.98 },
        maxWidth: layout.contentWidth * 0.9,
        maxLines: 2,
        minSize: Math.round(34 * layout.u),
        maxSize: Math.round(46 * layout.u),
      }),
    [content.headline, layout],
  );
  return (
    <div style={{ position: "absolute", left: layout.margin, top: layout.safeTop + layout.type.kicker * 3.1, width: layout.contentWidth * 0.9 }}>
      <TextReveal
        layout={compact}
        role={{ ...textRoles.breakingHeadline, lineHeight: 0.98 }}
        color="rgba(255,255,255,0.92)"
        accent={brand.colors.white}
        mode="line"
        delay={0.25}
        duration={0.5}
      />
    </div>
  );
};

export const BreakingNews: React.FC<TemplateProps> = ({ piece }) => (
  <PieceShell piece={piece}>
    <BreakingInner piece={piece} />
  </PieceShell>
);
