import React, { useMemo } from "react";
import { AbsoluteFill, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { brand } from "../brand/brand.config";
import { getCategory } from "../brand/categories";
import { BrandLogo, CategoryTag, Grain, MetaLine, Scrim } from "../components/brand";
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

/**
 * B · EDITORIAL NEWS. La imagen manda: video o foto a pantalla completa (o en
 * ventana grande sobre su propio fondo desenfocado), degradado violeta de la
 * marca abajo y titular en serif con la palabra clave en italica ambar.
 * Ritmo mas calmo que Breaking: barridas diagonales y camara lenta, sin
 * etiqueta de urgencia.
 */
const EditorialInner: React.FC<TemplateProps> = ({ piece }) => {
  const setup = useTemplateSetup(piece, "editorial");
  const { content, layout, accent, plan, hook } = setup;
  const frame = useCurrentFrame();
  const { fps, height } = useVideoConfig();
  const u = layout.u;
  const holdBeat = plan.beats.find((b) => b.kind === "hold");
  // En el tramo compacto el degradado baja y deja ver la imagen.
  const fullScrim = height * (layout.format === "reel" ? 0.64 : 0.7);
  const holdP = holdBeat ? ramp(frame, holdBeat.start - sec(0.3, fps), sec(0.6, fps), "glide") : 0;
  const scrimSize = fullScrim - holdP * fullScrim * 0.4;

  // Imagen apaisada: ventana grande (recorta como mucho 30% de los costados) sobre su fondo desenfocado.
  const windowRect = { top: Math.round(layout.safeTop * 0.6), height: Math.round(height * (layout.format === "reel" ? 0.52 : 0.6)) };
  const stage = <MediaStage content={content} plan={plan} layout={layout} cut="slash" accent={accent} windowRect={windowRect} />;

  return (
    <AbsoluteFill>
      {hook.revealsStage ? <ImageReveal duration={0.95} delay={-REVEAL_LEAD}>{stage}</ImageReveal> : stage}
      <AbsoluteFill style={{ background: "rgba(30,13,51,0.14)" }} />
      <Scrim from="bottom" size={scrimSize} strength={0.95} color="30,13,51" />
      <Scrim from="top" size={layout.safeTop + 240 * u} strength={0.55} color="30,13,51" />
      <Grain opacity={0.05} />

      {plan.beats.map((beat, i) => (
        <Sequence key={i} from={beat.start - (i === 0 ? sec(0.2, fps) : 0)} durationInFrames={beat.duration + (i === 0 ? sec(0.2, fps) : 0)} name={`Bloque ${beat.kind}`}>
          <EditorialBeat setup={setup} beat={beat} lead={i === 0 ? 0.2 : 0} isLast={i === plan.beats.length - 1} />
        </Sequence>
      ))}

      {/* Firma y lugar */}
      <Sequence durationInFrames={plan.outro.start} name="Firma">
        <div style={{ position: "absolute", left: layout.margin, top: layout.safeTop }}>
          <Rise delay={0.3} distance={10}>
            <BrandLogo height={Math.round(46 * u)} opacity={0.95} />
          </Rise>
        </div>
        {content.location ? (
          <div style={{ position: "absolute", right: layout.margin + layout.safeRight, top: layout.safeTop + 6 * u }}>
            <LocationTag text={content.location} fontSize={layout.type.meta} color={brand.colors.white} pinColor={accent} delay={plan.hook.duration / fps + 0.1} />
          </div>
        ) : null}
      </Sequence>

      <NewsStrip setup={setup} label={getCategory(content.category).label} />
      <HookLayer setup={setup} template="editorial" />
      <Sequence from={plan.outro.start} durationInFrames={plan.outro.duration} name="Cierre">
        <EndCard content={content} layout={layout} accent={accent} />
      </Sequence>
      <DemoMark content={content} layout={layout} />
    </AbsoluteFill>
  );
};

const EditorialBeat: React.FC<{ setup: TemplateSetup; beat: Beat; lead: number; isLast: boolean }> = ({ setup, beat, lead, isLast }) => {
  const { content, layout, accent } = setup;
  const { fps, height } = useVideoConfig();
  const cfg = useAnimationConfig();
  const u = layout.u;
  const total = beat.duration + Math.round(lead * fps);
  const exitAt = isLast || beat.kind === "hold" ? undefined : total - sec(0.34, fps, cfg.speed);
  const isReel = layout.format === "reel";
  const width = layout.contentWidth;

  const headline = useMemo(
    () =>
      fitTextBlock({
        text: content.headline,
        role: textRoles.editorialHeadline,
        maxWidth: width,
        maxLines: layout.format === "square" ? 3 : 4,
        preferLines: 3,
        minSize: Math.round(layout.type.headlineMin * 0.95),
        maxSize: Math.round(layout.type.headlineMax * 0.9),
        maxHeight: height * (isReel ? 0.28 : 0.32),
        emphasisItalic: true,
      }),
    [content.headline, width, layout, height, isReel],
  );
  const compact = useMemo(
    () =>
      fitTextBlock({
        text: content.headline,
        role: textRoles.editorialHeadline,
        maxWidth: width,
        maxLines: 3,
        preferLines: 2,
        minSize: Math.round(44 * u),
        maxSize: Math.round(64 * u),
        emphasisItalic: true,
      }),
    [content.headline, width, u],
  );

  const block = (children: React.ReactNode) => (
    <div style={{ position: "absolute", left: layout.margin, width, bottom: textBottom(layout), display: "flex", flexDirection: "column", gap: 26 * u }}>{children}</div>
  );
  const meta = !isReel ? <MetaLine date={content.date} source={content.source.name} fontSize={layout.type.meta} color="rgba(255,255,255,0.8)" separatorColor={accent} /> : null;

  if (beat.kind === "hold") {
    return block(
      <>
        <TextReveal layout={compact} role={textRoles.editorialHeadline} color={brand.colors.white} accent={accent} emphasisStyle="italic" mode="line" stagger={0.06} duration={0.6} delay={0.2} />
        {meta ? <Rise delay={0.5} distance={10}>{meta}</Rise> : null}
      </>,
    );
  }

  if (beat.kind === "headline") {
    const d0 = lead + 0.05;
    return block(
      <>
        <CategoryTag label={getCategory(content.category).label} accent={accent} fontSize={layout.type.kicker * 0.92} delay={d0} exitAt={exitAt} />
        <TextReveal
          layout={headline}
          role={textRoles.editorialHeadline}
          color={brand.colors.white}
          accent={accent}
          emphasisStyle="italic"
          mode="word"
          stagger={0.045}
          duration={0.65}
          easing="snap"
          delay={d0 + 0.12}
          exitAt={exitAt}
        />
        {meta ? (
          <Rise delay={d0 + 0.6} distance={12} exitAt={exitAt}>
            {meta}
          </Rise>
        ) : null}
      </>,
    );
  }

  const isQuote = beat.kind === "quote" && content.quote;
  const text = beat.kind === "deck" ? content.deck : beat.kind === "highlight" ? (content.highlights[beat.index] ?? "") : `“${content.quote?.text ?? ""}”`;
  const role = isQuote ? textRoles.quote : textRoles.deck;
  const para = layoutParagraph(text, role, Math.round((isQuote ? 64 : isReel ? 56 : 46) * u), width - 44 * u);
  const label = beat.kind === "deck" ? "Contexto" : beat.kind === "highlight" ? `Clave ${beat.index + 1}` : "Testimonio";
  return block(
    <>
      <Rise delay={0.04} distance={10} exitAt={exitAt}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 * u }}>
          <GrowBar length={44 * u} thickness={Math.max(3, 6 * u)} color={accent} delay={0.04} />
          <span style={{ ...roleStyle(textRoles.meta, layout.type.meta * 1.1), color: accent }}>{upper(label)}</span>
        </div>
      </Rise>
      <div style={{ display: "flex", gap: 34 * u, alignItems: "stretch" }}>
        <GrowBar axis="y" length={para.height} thickness={Math.round(8 * u)} color={accent} delay={0.08} duration={0.5} origin="end" />
        <div style={{ flex: 1 }}>
          <TextReveal layout={para} role={role} color={brand.colors.white} accent={accent} mode="line" delay={0.14} stagger={0.08} duration={0.7} easing="snap" exitAt={exitAt} />
        </div>
      </div>
      {isQuote && content.quote?.author ? (
        <Rise delay={0.6} distance={10} exitAt={exitAt}>
          <span style={{ ...roleStyle(textRoles.meta, layout.type.meta), color: "rgba(255,255,255,0.78)" }}>— {upper(content.quote.author)}</span>
        </Rise>
      ) : null}
    </>,
  );
};

export const EditorialNews: React.FC<TemplateProps> = ({ piece }) => (
  <PieceShell piece={piece}>
    <EditorialInner piece={piece} />
  </PieceShell>
);
