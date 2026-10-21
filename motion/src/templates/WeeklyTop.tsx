import React, { useMemo } from "react";
import { AbsoluteFill, interpolate, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { brand } from "../brand/brand.config";
import { getCategory } from "../brand/categories";
import { BrandLogo } from "../components/brand";
import { fitTextBlock } from "../design/textLayout";
import { roleStyle, textRoles, upper } from "../design/tokens";
import { Rise } from "../engine/animations/primitives";
import { TextReveal } from "../engine/animations/TextReveal";
import { ramp, sec } from "../engine/timing";
import { BrandFrame, extraOf, fmtNum, Photo, Tag } from "./formatKit";
import { EndCard, OUTRO_SECONDS, PieceShell, type TemplateProps } from "./shared";
import { getLayout } from "../design/layout";

/**
 * I · TOP 5 DE LA SEMANA (reel 9:16, domingos). Cuenta regresiva 5 -> 1 con las
 * notas mas vistas de los ultimos 7 dias segun las metricas guardadas. Cada
 * nota usa la foto o la portada que ya se publico. Duracion: 2 s de apertura,
 * 4 s por nota y el cierre de marca.
 */
export const WEEKLY_INTRO = 2.2;
export const WEEKLY_ITEM = 4;

type Item = { headline: string; photo?: string; views: number; category?: string; dateLabel?: string; source?: string };

const Intro: React.FC<{ range: string }> = ({ range }) => {
  const { width: W } = useVideoConfig();
  const u = W / 1080;
  const m = Math.round(80 * u);
  return (
    <BrandFrame corners={0.16}>
      <AbsoluteFill style={{ justifyContent: "center", padding: m, gap: 30 * u }}>
        <Rise delay={0.05} distance={40}>
          <BrandLogo height={Math.round(70 * u)} />
        </Rise>
        <Rise delay={0.15} distance={60}>
          <div style={{ ...roleStyle(textRoles.breakingHeadline, Math.round(190 * u)), whiteSpace: "normal", color: brand.colors.white }}>
            TOP <span style={{ color: brand.colors.accent }}>5</span>
            <br />
            DE LA SEMANA
          </div>
        </Rise>
        <Rise delay={0.35} distance={20}>
          <span style={{ ...roleStyle(textRoles.meta, Math.round(28 * u)), color: "rgba(255,255,255,0.8)" }}>{upper(range)} · LO MÁS VISTO EN DÚO</span>
        </Rise>
      </AbsoluteFill>
    </BrandFrame>
  );
};

const Slide: React.FC<{ item: Item; rank: number }> = ({ item, rank }) => {
  const frame = useCurrentFrame();
  const { fps, width: W } = useVideoConfig();
  const u = W / 1080;
  const m = Math.round(70 * u);
  const total = sec(WEEKLY_ITEM, fps);
  const zoom = interpolate(frame, [0, total], [1.04, 1.14]);
  const numP = ramp(frame, 0, sec(0.45, fps), "snap");
  const count = Math.round(item.views * ramp(frame, sec(0.5, fps), sec(1.4, fps), "glide"));
  const block = useMemo(
    () =>
      fitTextBlock({
        text: item.headline,
        role: textRoles.postHeadline,
        maxWidth: W - m * 2,
        maxLines: 4,
        preferLines: 3,
        minSize: Math.round(60 * u),
        maxSize: Math.round(96 * u),
        maxHeight: 440 * u,
      }),
    [item.headline, W, m, u],
  );
  const cat = getCategory(item.category);
  return (
    <AbsoluteFill style={{ background: brand.colors.ink }}>
      <AbsoluteFill style={{ scale: String(zoom) }}>
        <Photo src={item.photo} />
      </AbsoluteFill>
      <AbsoluteFill style={{ background: "linear-gradient(to bottom, rgba(12,8,18,0.65) 0%, rgba(12,8,18,0.1) 30%, rgba(12,8,18,0.25) 45%, rgba(12,8,18,0.92) 68%, rgba(12,8,18,0.97) 100%)" }} />
      <div style={{ position: "absolute", left: m, top: 250 * u, display: "flex", alignItems: "flex-end", gap: 20 * u, opacity: numP, translate: `${(1 - numP) * -80}px 0` }}>
        <span style={{ ...roleStyle(textRoles.dataNumber, Math.round(300 * u)), color: brand.colors.accent, textShadow: "0 8px 40px rgba(0,0,0,0.5)" }}>{rank}</span>
        <span style={{ ...roleStyle(textRoles.meta, Math.round(26 * u)), color: brand.colors.white, paddingBottom: 40 * u }}>DE 5</span>
      </div>
      <div style={{ position: "absolute", left: m, right: m, top: 1490 * u - block.height - 120 * u, display: "flex", flexDirection: "column", gap: 24 * u }}>
        <Rise delay={0.2} distance={24}>
          <Tag label={cat.label} color={cat.accent} size={Math.round(28 * u)} />
        </Rise>
        <TextReveal layout={block} role={textRoles.postHeadline} color={brand.colors.white} accent={brand.colors.accent} mode="word" delay={0.3} emphasisStyle="marker" markerTextColor={brand.colors.ink} />
        <Rise delay={0.6} distance={16}>
          <div style={{ display: "flex", alignItems: "center", gap: 16 * u }}>
            <span style={{ ...roleStyle(textRoles.dataNumber, Math.round(64 * u)), color: brand.colors.accent }}>{fmtNum(count)}</span>
            <span style={{ ...roleStyle(textRoles.kicker, Math.round(26 * u)), color: brand.colors.white }}>VISTAS</span>
            {item.dateLabel ? <span style={{ ...roleStyle(textRoles.meta, Math.round(21 * u)), color: "rgba(255,255,255,0.7)", marginLeft: 12 * u }}>{upper(item.dateLabel)}</span> : null}
          </div>
        </Rise>
      </div>
    </AbsoluteFill>
  );
};

export const WeeklyTop: React.FC<TemplateProps> = ({ piece }) => {
  const { fps, width, height } = useVideoConfig();
  const x = extraOf(piece.content);
  const items = ((x.items as Item[]) ?? []).slice(0, 5);
  const layout = getLayout("reel", width, height);
  const intro = sec(WEEKLY_INTRO, fps);
  const each = sec(WEEKLY_ITEM, fps);
  const ordered = [...items].reverse(); // 5 -> 1
  return (
    <PieceShell piece={piece}>
      <Sequence durationInFrames={intro} name="Apertura">
        <Intro range={String(x.rangeLabel ?? "")} />
      </Sequence>
      {ordered.map((item, i) => (
        <Sequence key={i} from={intro + i * each} durationInFrames={each} name={`Puesto ${items.length - i}`}>
          <Slide item={item} rank={items.length - i} />
        </Sequence>
      ))}
      <Sequence from={intro + ordered.length * each} durationInFrames={sec(OUTRO_SECONDS, fps)} name="Cierre">
        <EndCard content={piece.content} layout={layout} accent={brand.colors.accent} />
      </Sequence>
    </PieceShell>
  );
};

export const weeklySeconds = (count: number) => WEEKLY_INTRO + Math.min(5, count) * WEEKLY_ITEM + OUTRO_SECONDS;
