import React, { useMemo } from "react";
import { AbsoluteFill, interpolate, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { brand } from "../brand/brand.config";
import { getCategory } from "../brand/categories";
import { BrandLogo, Grain, MetaLine, Scrim } from "../components/brand";
import { MediaStage } from "../components/MediaStage";
import { fitTextBlock, layoutParagraph, measure, type TextBlockLayout } from "../design/textLayout";
import { roleStyle, textRoles, upper, type TextRole } from "../design/tokens";
import { parallelogram, slashRun } from "../engine/animations/geometry";
import { LocationTag } from "../engine/animations/editorial";
import { GrowBar, ImageReveal, Rise } from "../engine/animations/primitives";
import { TextReveal } from "../engine/animations/TextReveal";
import { REVEAL_LEAD } from "../engine/hooks/PhotoHook";
import type { Beat } from "../engine/timeline";
import { sec, springAt, useAnimationConfig } from "../engine/timing";
import { DemoMark, EndCard, HookLayer, PieceShell, type TemplateProps, type TemplateSetup, useTemplateSetup } from "./shared";

/**
 * B · EDITORIAL NEWS. Estetica de revista: la imagen arriba con camara lenta y
 * paralaje, un panel de papel con pestana diagonal que cambia de alto con
 * cada bloque, titular en serif optica, barridas diagonales entre fotos.
 */

type Palette = { panel: string; text: string; soft: string; rule: string };

const palettes: Record<"light" | "dark", Palette> = {
  light: { panel: brand.colors.paper, text: brand.colors.primaryDeep, soft: "#4A3F57", rule: "rgba(30,13,51,0.18)" },
  dark: { panel: brand.colors.inkSoft, text: brand.colors.white, soft: "rgba(255,255,255,0.78)", rule: "rgba(255,255,255,0.2)" },
};

type BeatContent = {
  beat: Beat;
  label: string;
  block: TextBlockLayout;
  role: TextRole;
  emphasisItalic: boolean;
  height: number;
  extra?: string;
};

const EditorialInner: React.FC<TemplateProps> = ({ piece }) => {
  const setup = useTemplateSetup(piece, "editorial");
  const { content, presentation, layout, accent, plan, hook } = setup;
  const frame = useCurrentFrame();
  const { fps, height } = useVideoConfig();
  const cfg = useAnimationConfig();
  const pal = palettes[presentation.theme];
  const u = layout.u;
  const padX = layout.margin;
  const padTop = Math.round(64 * u);
  const textWidth = layout.width - padX * 2 - layout.safeRight;

  // Contenido de cada bloque, medido de antemano (el panel anima su alto).
  const beats: BeatContent[] = useMemo(() => {
    return plan.beats.map((beat) => {
      if (beat.kind === "hold") {
        // Titular compacto: el panel se recoge y deja ver el video.
        const block = fitTextBlock({
          text: content.headline,
          role: textRoles.editorialHeadline,
          maxWidth: textWidth,
          maxLines: 3,
          preferLines: 2,
          minSize: Math.round(40 * u),
          maxSize: Math.round(58 * u),
          emphasisItalic: true,
        });
        return { beat, label: "", block, role: textRoles.editorialHeadline, emphasisItalic: true, height: block.height + Math.round(10 * u) };
      }
      if (beat.kind === "headline") {
        const block = fitTextBlock({
          text: content.headline,
          role: textRoles.editorialHeadline,
          maxWidth: textWidth,
          maxLines: layout.format === "square" ? 3 : 4,
          preferLines: 3,
          minSize: Math.round(layout.type.headlineMin * 0.95),
          maxSize: Math.round(layout.type.headlineMax * 0.84),
          maxHeight: height * (layout.format === "reel" ? 0.24 : 0.3),
          emphasisItalic: true,
        });
        return { beat, label: getCategory(content.category).label, block, role: textRoles.editorialHeadline, emphasisItalic: true, height: block.height + Math.round(110 * u) };
      }
      if (beat.kind === "quote" && content.quote) {
        const block = layoutParagraph(`“${content.quote.text}”`, textRoles.quote, Math.round(64 * u), textWidth);
        return { beat, label: "Testimonio", block, role: textRoles.quote, emphasisItalic: false, height: block.height + Math.round(110 * u), extra: content.quote.author };
      }
      const text = beat.kind === "deck" ? content.deck : (content.highlights[beat.index] ?? "");
      const block = layoutParagraph(text, textRoles.deck, Math.round((layout.format === "reel" ? 58 : 48) * u), textWidth);
      const label = beat.kind === "deck" ? "Contexto" : `Clave ${beat.index + 1}`;
      return { beat, label, block, role: textRoles.deck, emphasisItalic: false, height: block.height + Math.round(70 * u) };
    });
  }, [plan.beats, content, textWidth, layout, height, u]);

  // Alto del panel: transicion con spring entre los altos de cada bloque.
  // Reels: el texto queda sobre la zona del caption de Instagram, sin dejar un panel vacio enorme.
  const bottomInset = layout.format === "reel" ? layout.safeBottom - Math.round(110 * u) : layout.margin;
  const panelHeightFor = (b: BeatContent) => b.height + padTop + bottomInset + Math.round(40 * u);
  let panelH = beats.length ? panelHeightFor(beats[0]) : 0;
  for (let i = 1; i < beats.length; i++) {
    const s = springAt(frame, fps, beats[i].beat.start - sec(0.2, fps, cfg.speed), { stiffness: 120, damping: 24 });
    panelH = interpolate(s, [0, 1], [panelH, panelHeightFor(beats[i])]);
  }
  // El panel sube al final del gancho, justo antes del titular.
  const panelIn = springAt(frame, fps, Math.max(sec(0.2, fps, cfg.speed), plan.hook.duration - sec(0.6, fps, cfg.speed)), { stiffness: 110, damping: 20 });
  const panelY = interpolate(panelIn, [0, 1], [panelH + 80 * u, 0]);
  const panelTop = layout.height - panelH;

  // La ventana de imagen se centra en el espacio libre sobre el panel inicial.
  const firstPanelTop = layout.height - (beats.length ? panelHeightFor(beats[0]) : 0);
  // La imagen ocupa todo el espacio libre sobre el panel (a sangre arriba).
  const windowRect = { top: 0, height: firstPanelTop + Math.round(70 * u) };

  const panelStart = Math.max(sec(0.2, fps, cfg.speed), plan.hook.duration - sec(0.6, fps, cfg.speed));
  const stage = (
    <MediaStage content={content} plan={plan} layout={layout} cut="slash" accent={accent} windowRect={windowRect} windowIntro={{ startFrame: panelStart }} />
  );
  const tabH = Math.round(66 * u);
  const tabRun = slashRun(tabH);
  const categoryLabel = upper(getCategory(content.category).label);
  const tabFont = layout.type.kicker * 0.92;
  const tabW = Math.round(measure(categoryLabel, textRoles.kicker, tabFont) + tabRun * 2 + 64 * u);

  return (
    <AbsoluteFill>
      {hook.revealsStage ? <ImageReveal duration={0.95} delay={-REVEAL_LEAD}>{stage}</ImageReveal> : stage}
      <Scrim from="top" size={layout.safeTop + 220 * u} strength={0.5} />
      <Grain opacity={0.05} />

      {/* Firma superior discreta */}
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

      {/* Panel editorial */}
      <Sequence from={0} durationInFrames={plan.outro.start + 6} name="Panel">
        <div style={{ position: "absolute", left: 0, right: 0, top: panelTop, height: panelH + 4, translate: `0 ${panelY}px` }}>
          {/* Pestana de categoria con la pendiente de la marca */}
          <div
            style={{
              position: "absolute",
              left: padX - tabRun * 0.5,
              top: -tabH + 1,
              height: tabH,
              width: tabW,
              background: pal.panel,
              clipPath: parallelogram(tabW, tabH),
              display: "flex",
              alignItems: "center",
              paddingLeft: tabRun + 18 * u,
            }}
          >
            <div style={{ width: 14 * u, height: 14 * u, background: accent, marginRight: 14 * u, rotate: "45deg" }} />
            <span style={{ ...roleStyle(textRoles.kicker, tabFont), color: pal.text }}>{categoryLabel}</span>
          </div>
          <div style={{ position: "absolute", inset: 0, background: pal.panel }} />
          <div style={{ position: "absolute", left: 0, top: 0, height: Math.max(4, 8 * u), width: "100%", background: accent }} />
          {beats.map((b, i) => (
            <Sequence key={i} from={b.beat.start - (i === 0 ? sec(0.3, fps) : 0)} durationInFrames={b.beat.duration + (i === 0 ? sec(0.3, fps) : 0)} layout="none" name={`Bloque ${b.beat.kind}`}>
              <EditorialBeat setup={setup} content={b} pal={pal} padX={padX} padTop={padTop} isLast={i === beats.length - 1} />
            </Sequence>
          ))}
        </div>
      </Sequence>

      <HookLayer setup={setup} template="editorial" />
      <Sequence from={plan.outro.start} durationInFrames={plan.outro.duration} name="Cierre">
        <EndCard content={content} layout={layout} accent={accent} />
      </Sequence>
      <DemoMark content={content} layout={layout} />
    </AbsoluteFill>
  );
};

const EditorialBeat: React.FC<{
  setup: TemplateSetup;
  content: BeatContent;
  pal: Palette;
  padX: number;
  padTop: number;
  isLast: boolean;
}> = ({ setup, content: b, pal, padX, padTop, isLast }) => {
  const { content, layout, accent } = setup;
  const { fps } = useVideoConfig();
  const cfg = useAnimationConfig();
  const u = layout.u;
  const total = b.beat.duration + (b.beat.kind === "headline" ? sec(0.3, fps) : 0);
  const exitAt = isLast || b.beat.kind === "hold" ? undefined : total - sec(0.34, fps, cfg.speed);
  const isHold = b.beat.kind === "hold";
  const isHeadline = b.beat.kind === "headline" || isHold;
  const d0 = isHold ? 0.25 : isHeadline ? 0.2 : 0.1;
  return (
    <div style={{ position: "absolute", left: padX, right: padX + layout.safeRight, top: padTop }}>
      {!isHeadline ? (
        <Rise delay={0.04} distance={10} exitAt={exitAt} style={{ marginBottom: 22 * u }}>
          <div style={{ display: "flex", alignItems: "center", gap: 16 * u }}>
            <GrowBar length={44 * u} thickness={Math.max(3, 5 * u)} color={accent} delay={0.04} />
            <span style={{ ...roleStyle(textRoles.meta, layout.type.meta), color: pal.soft }}>{upper(b.label)}</span>
          </div>
        </Rise>
      ) : null}
      <TextReveal
        layout={b.block}
        role={b.role}
        color={pal.text}
        accent={b.beat.kind === "quote" ? pal.text : accentOnPanel(accent, pal)}
        emphasisStyle="italic"
        mode={isHeadline && !isHold ? "word" : "line"}
        stagger={isHeadline ? 0.04 : 0.08}
        duration={isHeadline ? 0.6 : 0.7}
        easing="snap"
        delay={d0}
        exitAt={exitAt}
      />
      {isHeadline && !isHold ? (
        <Rise delay={d0 + 0.6} distance={12} exitAt={exitAt} style={{ marginTop: 30 * u }}>
          <MetaLine date={content.date} source={content.source.name} fontSize={layout.type.meta} color={pal.soft} separatorColor={accent} />
        </Rise>
      ) : null}
      {b.extra ? (
        <Rise delay={0.6} distance={10} exitAt={exitAt} style={{ marginTop: 26 * u }}>
          <span style={{ ...roleStyle(textRoles.meta, layout.type.meta), color: pal.soft }}>— {upper(b.extra)}</span>
        </Rise>
      ) : null}
    </div>
  );
};

/** Sobre papel, los acentos claros (ambar) pierden contraste: se usa el violeta. */
const accentOnPanel = (accent: string, pal: Palette) => (pal.panel === brand.colors.paper ? brand.colors.primary : accent);

export const EditorialNews: React.FC<TemplateProps> = ({ piece }) => (
  <PieceShell piece={piece}>
    <EditorialInner piece={piece} />
  </PieceShell>
);
