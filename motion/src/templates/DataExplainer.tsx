import React, { useMemo } from "react";
import { AbsoluteFill, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { brand } from "../brand/brand.config";
import { getCategory } from "../brand/categories";
import { BrandLogo, CategoryTag, Grain, MetaLine, Scrim } from "../components/brand";
import { MediaStage } from "../components/MediaStage";
import { fitSingleLine, fitTextBlock, layoutParagraph } from "../design/textLayout";
import { roleStyle, textRoles, upper } from "../design/tokens";
import { NumberCounter } from "../engine/animations/editorial";
import { GrowBar, Rise } from "../engine/animations/primitives";
import { TextReveal } from "../engine/animations/TextReveal";
import type { Beat } from "../engine/timeline";
import { ramp, sec, useAnimationConfig } from "../engine/timing";
import type { Stat } from "../schema/piece";
import { DemoMark, EndCard, HookLayer, NewsStrip, PieceShell, textBottom, type TemplateProps, type TemplateSetup, useTemplateSetup } from "./shared";

/**
 * C · DATA EXPLAINER. Las cifras son protagonistas: contadores, barras de
 * comparacion y medidores sobre un tablero violeta con grilla tenue; entre
 * cifras, la foto vuelve con el titular. Todas las cifras salen de
 * `content.stats` (nunca se inventan ni se completan).
 */
const DataInner: React.FC<TemplateProps> = ({ piece }) => {
  const setup = useTemplateSetup(piece, "data");
  const { content, layout, accent, plan } = setup;
  const statBeats = plan.beats.filter((b) => b.kind === "stat");
  const boardStart = statBeats.length ? statBeats[0].start : 0;
  const boardEnd = statBeats.length ? statBeats[statBeats.length - 1].start + statBeats[statBeats.length - 1].duration : 0;
  const { height } = useVideoConfig();

  return (
    <AbsoluteFill>
      {/* La foto ocupa la mitad superior en todo el reel (tambien detras de las cifras) */}
      <MediaStage
        content={content}
        plan={plan}
        layout={layout}
        cut="fade"
        accent={accent}
        windowRect={{ top: 0, height: Math.round(height * (layout.format === "reel" ? 0.6 : 0.66)) }}
        band={{ top: 0, height: Math.round(height * (layout.format === "reel" ? 0.6 : 0.66)), fade: 0.34 }}
        bandBackground={`linear-gradient(to bottom, ${brand.colors.primaryDeep}, ${brand.colors.primary})`}
      />
      <AbsoluteFill style={{ background: "rgba(30,13,51,0.28)" }} />
      <Scrim from="bottom" size={height * 0.66} strength={0.92} color="30,13,51" />
      <Scrim from="top" size={layout.safeTop + 220 * layout.u} strength={0.55} color="30,13,51" />

      {plan.beats
        .filter((b) => b.kind !== "stat")
        .map((beat, i) => (
          <Sequence key={`t${i}`} from={beat.start} durationInFrames={beat.duration} name={`Bloque ${beat.kind}`}>
            <DataTextBeat setup={setup} beat={beat} />
          </Sequence>
        ))}

      {statBeats.length ? (
        <Sequence from={boardStart} durationInFrames={boardEnd - boardStart} name="Tablero de datos">
          <Board setup={setup} durationFrames={boardEnd - boardStart} closes={boardEnd < plan.outro.start} />
          {statBeats.map((beat, i) => (
            <Sequence key={`s${i}`} from={beat.start - boardStart} durationInFrames={beat.duration} name={`Cifra ${beat.index + 1}`}>
              <StatBeat setup={setup} beat={beat} stat={content.stats[beat.index]} total={content.stats.length} isLast={i === statBeats.length - 1 && boardEnd >= plan.outro.start} />
            </Sequence>
          ))}
        </Sequence>
      ) : null}

      <Sequence durationInFrames={plan.outro.start} name="Firma">
        <div style={{ position: "absolute", left: layout.margin, top: layout.safeTop }}>
          <Rise delay={0.3} distance={10}>
            <BrandLogo height={Math.round(46 * layout.u)} opacity={0.95} />
          </Rise>
        </div>
      </Sequence>
      <Grain opacity={0.05} />
      <NewsStrip setup={setup} label={getCategory(content.category).label} />
      <HookLayer setup={setup} template="data" />
      <Sequence from={plan.outro.start} durationInFrames={plan.outro.duration} name="Cierre">
        <EndCard content={content} layout={layout} accent={accent} />
      </Sequence>
      <DemoMark content={content} layout={layout} />
    </AbsoluteFill>
  );
};

/** Tablero: degradado violeta que entra y sale con fundido (sin cortes bruscos). */
const Board: React.FC<{ setup: TemplateSetup; durationFrames: number; closes: boolean }> = ({ setup, durationFrames, closes }) => {
  const { layout } = setup;
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const exitAt = durationFrames - sec(0.5, fps);
  const out = closes ? ramp(frame, exitAt, sec(0.5, fps), "glide") : 0;
  const inP = ramp(frame, 0, sec(0.6, fps), "glide");
  const cols = 12;
  return (
    <AbsoluteFill style={{ opacity: inP * (1 - out) }}>
      <AbsoluteFill>
        {/* Degradado violeta: la foto sigue visible arriba, las cifras se leen sobre color pleno */}
        <AbsoluteFill style={{ background: `linear-gradient(to bottom, rgba(54,25,87,0) 0%, rgba(54,25,87,0.18) 24%, rgba(54,25,87,0.82) 40%, ${brand.colors.primary} 54%)` }}>
          {/* Grilla de columnas tenue en la zona de datos */}
          <svg width={width} height={height} style={{ position: "absolute", inset: 0, opacity: 0.1, maskImage: "linear-gradient(to bottom, transparent 35%, #000 60%)", WebkitMaskImage: "linear-gradient(to bottom, transparent 35%, #000 60%)" }}>
            {Array.from({ length: cols + 1 }).map((_, i) => {
              const x = layout.margin + ((layout.contentWidth + layout.gutter) / cols) * i - (i === cols ? layout.gutter : 0);
              return <rect key={i} x={x} y={0} width={Math.max(1, 1.5 * layout.u)} height={height} fill={brand.colors.white} />;
            })}
          </svg>
        </AbsoluteFill>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const fmt = (v: number, decimals: number) => new Intl.NumberFormat("es-AR", { minimumFractionDigits: decimals, maximumFractionDigits: decimals }).format(v);

const StatBeat: React.FC<{ setup: TemplateSetup; beat: Beat; stat: Stat | undefined; total: number; isLast: boolean }> = ({
  setup,
  beat,
  stat,
  total,
  isLast,
}) => {
  const { content, layout, accent } = setup;
  const { fps } = useVideoConfig();
  const cfg = useAnimationConfig();
  const u = layout.u;
  const exitAt = isLast ? undefined : beat.duration - sec(0.3, fps, cfg.speed);
  const label = useMemo(
    () =>
      stat
        ? fitTextBlock({
            text: stat.label,
            role: textRoles.deckStrong,
            maxWidth: layout.contentWidth,
            maxLines: 3,
            minSize: Math.round(44 * u),
            maxSize: Math.round(64 * u),
          })
        : null,
    [stat, layout.contentWidth, u],
  );
  if (!stat || !label) return null;
  const finalText = `${stat.prefix ?? ""}${fmt(stat.value, stat.decimals)}${stat.unit && stat.unit.length <= 2 ? stat.unit : ""}`;
  const numberSize = fitSingleLine(finalText, textRoles.dataNumber, layout.contentWidth * 0.96, Math.round(layout.type.data * 1.4));
  const isPercent = stat.unit === "%" && stat.value >= 0 && stat.value <= 100;
  const hasCompare = stat.compareValue !== undefined;
  // Bloque centrado en el area util (entre cromo superior y zona de caption).
  const vizH = hasCompare ? 190 * u : isPercent ? 54 * u : 14 * u;
  const blockH = layout.type.meta * 1.4 + 26 * u + numberSize * 0.88 + 18 * u + label.height + 64 * u + vizH + (layout.format !== "reel" ? 56 * u + layout.type.meta * 1.2 : 0);
  // Anclado abajo (sobre el zocalo): la mitad superior queda para la foto.
  const areaTop = layout.safeTop + 90 * u;
  const areaBottom = layout.height - textBottom(layout);
  const top = Math.max(areaTop, areaBottom - blockH);
  const barW = layout.contentWidth;

  return (
    <div style={{ position: "absolute", left: layout.margin, top, width: layout.contentWidth }}>
      <Rise delay={0.05} distance={10} exitAt={exitAt}>
        <span style={{ ...roleStyle(textRoles.meta, layout.type.meta * 1.1), color: accent }}>
          {String(beat.index + 1).padStart(2, "0")} / {String(total).padStart(2, "0")} · {upper(getCategory(content.category).label)}
        </span>
      </Rise>
      <Rise delay={0} distance={0} exitAt={exitAt} style={{ marginTop: 26 * u }}>
        <NumberCounter
          value={stat.value}
          fromValue={hasCompare ? stat.compareValue : 0}
          decimals={stat.decimals}
          prefix={stat.prefix}
          unit={stat.unit}
          fontSize={numberSize}
          color={brand.colors.white}
          unitColor={accent}
          delay={0.12}
          duration={1.25}
        />
      </Rise>
      <div style={{ marginTop: 18 * u }}>
        <TextReveal layout={label} role={textRoles.deckStrong} color={brand.colors.white} accent={accent} mode="line" delay={0.4} exitAt={exitAt} />
      </div>

      {/* Visualizacion: comparacion, medidor o regla */}
      <Rise delay={0.55} distance={16} exitAt={exitAt} style={{ marginTop: 64 * u }}>
        {hasCompare ? (
          <CompareBars
            current={stat.value}
            previous={stat.compareValue as number}
            previousLabel={stat.compareLabel ?? "Anterior"}
            decimals={stat.decimals}
            unit={stat.unit}
            width={barW}
            u={u}
            accent={accent}
            fontSize={layout.type.meta}
          />
        ) : isPercent ? (
          <Gauge value={stat.value} width={barW} u={u} accent={accent} />
        ) : (
          <GrowBar length={barW * 0.42} thickness={Math.round(14 * u)} color={accent} delay={0.6} duration={0.7} />
        )}
      </Rise>
      {layout.format !== "reel" ? (
        <Rise delay={0.9} distance={8} exitAt={exitAt} style={{ marginTop: 56 * u }}>
          <MetaLine source={content.source.name} fontSize={layout.type.meta} color="rgba(255,255,255,0.7)" />
        </Rise>
      ) : null}
    </div>
  );
};

const CompareBars: React.FC<{
  current: number;
  previous: number;
  previousLabel: string;
  decimals: number;
  unit?: string;
  width: number;
  u: number;
  accent: string;
  fontSize: number;
}> = ({ current, previous, previousLabel, decimals, unit = "", width, u, accent, fontSize }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const max = Math.max(Math.abs(current), Math.abs(previous)) || 1;
  const p1 = ramp(frame, sec(0.6, fps), sec(0.8, fps), "snap");
  const p2 = ramp(frame, sec(0.75, fps), sec(0.9, fps), "snap");
  const rows = [
    { label: previousLabel, value: previous, color: "rgba(255,255,255,0.32)", p: p1 },
    { label: "Ahora", value: current, color: accent, p: p2 },
  ];
  const barH = Math.round(30 * u);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 26 * u }}>
      {rows.map((r) => (
        <div key={r.label}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 * u, ...roleStyle(textRoles.meta, fontSize), color: brand.colors.white }}>
            <span>{upper(r.label)}</span>
            <span>
              {fmt(r.value, decimals)}
              {unit}
            </span>
          </div>
          <div style={{ height: barH, background: "rgba(255,255,255,0.08)" }}>
            <div style={{ height: barH, width: (width * Math.abs(r.value)) / max, background: r.color, transformOrigin: "left center", scale: `${r.p} 1` }} />
          </div>
        </div>
      ))}
    </div>
  );
};

/** Medidor 0-100 en segmentos: lectura instantanea de un porcentaje. */
const Gauge: React.FC<{ value: number; width: number; u: number; accent: string }> = ({ value, width, u, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const segments = 20;
  const gap = Math.round(6 * u);
  const segW = (width - gap * (segments - 1)) / segments;
  const lit = (value / 100) * segments * ramp(frame, sec(0.6, fps), sec(1.0, fps), "snap");
  return (
    <div style={{ display: "flex", gap }}>
      {Array.from({ length: segments }).map((_, i) => {
        const fill = Math.max(0, Math.min(1, lit - i));
        return (
          <div key={i} style={{ width: segW, height: Math.round(54 * u), background: "rgba(255,255,255,0.1)", position: "relative" }}>
            <div style={{ position: "absolute", inset: 0, background: accent, transformOrigin: "left center", scale: `${fill} 1` }} />
          </div>
        );
      })}
    </div>
  );
};

/** Titular y bajada sobre la foto (entre cifras). */
const DataTextBeat: React.FC<{ setup: TemplateSetup; beat: Beat }> = ({ setup, beat }) => {
  const { content, layout, accent } = setup;
  const { fps, height } = useVideoConfig();
  const cfg = useAnimationConfig();
  const exitAt = beat.duration - sec(0.3, fps, cfg.speed);
  const headline = useMemo(
    () =>
      fitTextBlock({
        text: content.headline,
        role: textRoles.postHeadline,
        maxWidth: layout.contentWidth,
        maxLines: layout.type.headlineLines,
        preferLines: layout.type.headlinePrefer,
        minSize: layout.type.headlineMin,
        maxSize: Math.round(layout.type.headlineMax * 0.92),
        maxHeight: height * 0.3,
      }),
    [content.headline, layout, height],
  );
  const deck = useMemo(() => layoutParagraph(content.deck || "", textRoles.deck, Math.round(56 * layout.u), layout.contentWidth), [content.deck, layout]);
  return (
    <div style={{ position: "absolute", left: layout.margin, width: layout.contentWidth, bottom: textBottom(layout), display: "flex", flexDirection: "column", gap: 28 * layout.u }}>
      {beat.kind === "headline" ? (
        <>
          <CategoryTag label={getCategory(content.category).label} accent={accent} fontSize={layout.type.kicker * 0.92} delay={0.05} exitAt={exitAt} />
          <TextReveal layout={headline} role={textRoles.postHeadline} color={brand.colors.white} accent={accent} emphasisStyle="color" mode="word" delay={0.12} stagger={0.045} exitAt={exitAt} />
          {layout.format !== "reel" ? (
            <Rise delay={0.6} distance={12} exitAt={exitAt}>
              <MetaLine date={content.date} source={content.source.name} fontSize={layout.type.meta} color="rgba(255,255,255,0.8)" separatorColor={accent} />
            </Rise>
          ) : null}
        </>
      ) : (
        <TextReveal layout={deck} role={textRoles.deck} color={brand.colors.white} accent={accent} mode="line" delay={0.12} />
      )}
    </div>
  );
};

export const DataExplainer: React.FC<TemplateProps> = ({ piece }) => (
  <PieceShell piece={piece}>
    <DataInner piece={piece} />
  </PieceShell>
);
