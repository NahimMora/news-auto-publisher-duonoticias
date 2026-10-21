import React, { useMemo } from "react";
import { AbsoluteFill, Img, useVideoConfig } from "remotion";
import { brand } from "../brand/brand.config";
import { getCategory } from "../brand/categories";
import { BrandLogo } from "../components/brand";
import { FontGate } from "../components/FontGate";
import { resolveSrc } from "../components/media";
import { fitTextBlock } from "../design/textLayout";
import { roleStyle, textRoles, upper } from "../design/tokens";
import { TextReveal } from "../engine/animations/TextReveal";
import { BrandFrame, extraOf, fmtNum, Photo, SourceLine, T, Tag, type Extra } from "./formatKit";
import type { TemplateProps } from "./shared";

/**
 * H · HISTORIA (still 9:16). Instagram tapa ~250 px arriba (barra de progreso y
 * perfil) y ~260 px abajo (responder): todo lo importante vive entre y=270 y
 * y=1650. Variantes por `content.extra.kind`:
 * - story-post: el post recien publicado, enmarcado, con aviso de "nuevo post".
 * - story-breaking: ultimo momento.
 * - story-recap: lo mas importante del dia (5 notas con sus vistas).
 * - story-update: noticia en desarrollo (dato anterior -> dato nuevo).
 */

const TOP = 270;
const BOTTOM = 1650;

const useHeadline = (text: string, maxWidth: number, min: number, max: number, maxHeight: number, lines = 4) =>
  useMemo(
    () => fitTextBlock({ text, role: textRoles.postHeadline, maxWidth, maxLines: lines, preferLines: 3, minSize: min, maxSize: max, maxHeight }),
    [text, maxWidth, min, max, maxHeight, lines],
  );

const Head: React.FC<{ u: number; m: number; label: string; color?: string; textColor?: string }> = ({ u, m, label, color, textColor }) => (
  <div style={{ position: "absolute", left: m, right: m, top: TOP * u, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
    <Tag label={label} color={color} textColor={textColor} size={Math.round(30 * u)} />
    <BrandLogo height={Math.round(50 * u)} />
  </div>
);

const PostStory: React.FC<{ x: Extra }> = ({ x }) => {
  const { width: W } = useVideoConfig();
  const u = W / 1080;
  const m = Math.round(70 * u);
  const cardW = W - m * 2;
  const cardH = Math.round(cardW * 1.25);
  const top = Math.round(400 * u);
  return (
    <BrandFrame corners={0.12}>
      <Head u={u} m={m} label="Nuevo en el feed" />
      <div style={{ position: "absolute", left: m, top, width: cardW, height: cardH, boxShadow: "0 30px 80px rgba(0,0,0,0.55)", rotate: "-1.6deg", outline: `${6 * u}px solid ${brand.colors.white}` }}>
        <Img src={resolveSrc(String(x.image))} style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} />
      </div>
      <div style={{ position: "absolute", left: m, right: m, top: top + cardH + 70 * u, display: "flex", flexDirection: "column", alignItems: "center", gap: 18 * u }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 * u, padding: `${18 * u}px ${30 * u}px`, background: brand.colors.white, borderRadius: 60 * u }}>
          <span style={{ ...roleStyle(textRoles.kicker, Math.round(28 * u)), color: brand.colors.ink }}>MIRÁ LA NOTA EN EL PERFIL</span>
          <svg width={34 * u} height={34 * u} viewBox="0 0 24 24">
            <path d="M5 12h12M12 5l7 7-7 7" stroke={brand.colors.ink} strokeWidth="3" fill="none" />
          </svg>
        </div>
        <SourceLine text={brand.handle} size={Math.round(22 * u)} color="rgba(255,255,255,0.8)" />
      </div>
    </BrandFrame>
  );
};

const BreakingStory: React.FC<{ x: Extra }> = ({ x }) => {
  const { width: W } = useVideoConfig();
  const u = W / 1080;
  const m = Math.round(70 * u);
  const block = useHeadline(String(x.headline ?? ""), W - m * 2, Math.round(70 * u), Math.round(118 * u), 620 * u, 5);
  return (
    <AbsoluteFill style={{ background: brand.colors.ink }}>
      <Photo src={x.photo as string} />
      <AbsoluteFill style={{ background: `linear-gradient(to bottom, rgba(12,8,18,0.7) 0%, rgba(12,8,18,0.15) 28%, rgba(12,8,18,0.35) 48%, rgba(12,8,18,0.94) 72%, rgba(12,8,18,0.98) 100%)` }} />
      <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 16 * u, background: brand.colors.signal }} />
      <Head u={u} m={m} label={brand.copy.breakingLabel} color={brand.colors.signal} textColor={brand.colors.white} />
      <div style={{ position: "absolute", left: m, right: m, top: (BOTTOM - 120) * u - block.height - 70 * u, display: "flex", flexDirection: "column", gap: 26 * u }}>
        {x.location ? <span style={{ ...roleStyle(textRoles.kicker, Math.round(28 * u)), color: brand.colors.accent }}>📍 {upper(String(x.location))}</span> : null}
        <TextReveal layout={block} role={textRoles.postHeadline} color={brand.colors.white} accent={brand.colors.accent} mode="none" emphasisStyle="marker" markerTextColor={brand.colors.ink} />
      </div>
      <div style={{ position: "absolute", left: m, right: m, top: (BOTTOM - 90) * u, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ ...roleStyle(textRoles.kicker, Math.round(26 * u)), color: brand.colors.white }}>MÁS INFO EN EL POST ↗</span>
        <SourceLine text={String(x.time ?? "")} size={Math.round(22 * u)} />
      </div>
    </AbsoluteFill>
  );
};

const RecapStory: React.FC<{ x: Extra }> = ({ x }) => {
  const { width: W } = useVideoConfig();
  const u = W / 1080;
  const m = Math.round(64 * u);
  const items = (x.items as { headline: string; photo?: string; views?: number; category?: string }[]) ?? [];
  const rowH = Math.round(208 * u);
  return (
    <BrandFrame corners={0.07} tone="deep">
      <Head u={u} m={m} label="Lo más importante del día" />
      <div style={{ position: "absolute", left: m, right: m, top: (TOP + 90) * u }}>
        <span style={{ ...roleStyle(textRoles.meta, Math.round(24 * u)), color: "rgba(255,255,255,0.8)" }}>{upper(String(x.dateLabel ?? ""))}</span>
      </div>
      <div style={{ position: "absolute", left: m, right: m, top: (TOP + 150) * u, display: "flex", flexDirection: "column", gap: 22 * u }}>
        {items.map((it, i) => (
          <div key={i} style={{ display: "flex", gap: 22 * u, height: rowH, background: "rgba(255,255,255,0.07)", alignItems: "stretch" }}>
            <div style={{ position: "relative", width: rowH, flex: "none", overflow: "hidden" }}>
              <Photo src={it.photo} />
              <div style={{ position: "absolute", left: 0, top: 0, padding: `${4 * u}px ${14 * u}px`, background: brand.colors.accent }}>
                <span style={{ ...roleStyle(textRoles.dataNumber, Math.round(44 * u)), color: brand.colors.ink }}>{i + 1}</span>
              </div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", gap: 10 * u, paddingRight: 20 * u, minWidth: 0 }}>
              <span style={{ ...roleStyle(textRoles.kicker, Math.round(19 * u)), color: getCategory(it.category).accent }}>{upper(getCategory(it.category).label)}</span>
              <T role={textRoles.deckStrong} size={Math.round(31 * u)} lines={3}>
                {it.headline.replace(/\*/g, "")}
              </T>
              {it.views ? <span style={{ ...roleStyle(textRoles.meta, Math.round(19 * u)), color: "rgba(255,255,255,0.7)" }}>👁 {fmtNum(it.views)} VISTAS</span> : null}
            </div>
          </div>
        ))}
      </div>
      <div style={{ position: "absolute", left: m, right: m, top: (BOTTOM - 40) * u, display: "flex", justifyContent: "center" }}>
        <span style={{ ...roleStyle(textRoles.kicker, Math.round(24 * u)), color: brand.colors.accent }}>TODAS LAS NOTAS EN {upper(brand.handle)}</span>
      </div>
    </BrandFrame>
  );
};

const UpdateStory: React.FC<{ x: Extra }> = ({ x }) => {
  const { width: W } = useVideoConfig();
  const u = W / 1080;
  const m = Math.round(70 * u);
  const before = x.before as { value: string; label: string; time: string; source: string } | undefined;
  const after = x.after as { value: string; label: string; time: string; source: string } | undefined;
  const timeLabel = after?.time ?? String(x.timeLabel ?? "");
  const block = useHeadline(String(x.headline ?? ""), W - m * 2, Math.round(64 * u), Math.round(100 * u), 400 * u, 4);
  const photoH = Math.round(620 * u);
  return (
    <BrandFrame corners={0}>
      <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: (TOP * u) + photoH, overflow: "hidden" }}>
        <Photo src={x.photo as string} />
        <AbsoluteFill style={{ background: `linear-gradient(to bottom, rgba(30,13,51,0.55) 0%, rgba(30,13,51,0.1) 35%, ${brand.colors.primaryDeep} 100%)` }} />
      </div>
      <Head u={u} m={m} label={brand.copy.developingLabel} color={brand.colors.accent} />
      <div style={{ position: "absolute", left: m, right: m, top: (TOP + 470) * u, display: "flex", flexDirection: "column", gap: 34 * u }}>
        <span style={{ ...roleStyle(textRoles.kicker, Math.round(30 * u)), color: brand.colors.accent }}>⟳ ACTUALIZACIÓN{timeLabel ? ` · ${upper(timeLabel)}` : ""}</span>
        <TextReveal layout={block} role={textRoles.postHeadline} color={brand.colors.white} accent={brand.colors.accent} mode="none" emphasisStyle="marker" markerTextColor={brand.colors.ink} />
        {before && after ? (
        <div style={{ display: "flex", alignItems: "stretch", gap: 18 * u, marginTop: 10 * u }}>
          <div style={{ flex: 1, padding: `${30 * u}px`, background: "rgba(255,255,255,0.07)", display: "flex", flexDirection: "column", gap: 8 * u }}>
            <span style={{ ...roleStyle(textRoles.meta, Math.round(22 * u)), color: "rgba(255,255,255,0.7)" }}>ANTES · {upper(before.time)}</span>
            <span style={{ ...roleStyle(textRoles.dataNumber, Math.round(190 * u)), color: "rgba(255,255,255,0.45)", textDecoration: "line-through", textDecorationThickness: 6 * u }}>{before.value}</span>
            <T role={textRoles.deck} size={Math.round(34 * u)} color="rgba(255,255,255,0.7)">
              {before.label}
            </T>
            <SourceLine text={before.source} size={Math.round(20 * u)} color="rgba(255,255,255,0.5)" />
          </div>
          <div style={{ display: "flex", alignItems: "center" }}>
            <svg width={50 * u} height={50 * u} viewBox="0 0 24 24">
              <path d="M4 12h14M12 5l7 7-7 7" stroke={brand.colors.accent} strokeWidth="3" fill="none" />
            </svg>
          </div>
          <div style={{ flex: 1, padding: `${30 * u}px`, background: brand.colors.accent, display: "flex", flexDirection: "column", gap: 8 * u }}>
            <span style={{ ...roleStyle(textRoles.meta, Math.round(22 * u)), color: brand.colors.ink }}>AHORA · {upper(after.time)}</span>
            <span style={{ ...roleStyle(textRoles.dataNumber, Math.round(190 * u)), color: brand.colors.ink }}>{after.value}</span>
            <T role={textRoles.deckStrong} size={Math.round(34 * u)} color={brand.colors.ink}>
              {after.label}
            </T>
            <SourceLine text={after.source} size={Math.round(20 * u)} color="rgba(12,8,18,0.7)" />
          </div>
        </div>
        ) : null}
      </div>
      <div style={{ position: "absolute", left: m, right: m, top: (BOTTOM - 40) * u, display: "flex", justifyContent: "center" }}>
        <span style={{ ...roleStyle(textRoles.kicker, Math.round(24 * u)), color: brand.colors.white }}>SEGUIMOS LA COBERTURA EN {upper(brand.handle)}</span>
      </div>
    </BrandFrame>
  );
};

const StoryInner: React.FC<TemplateProps> = ({ piece }) => {
  const x = extraOf(piece.content);
  switch (x.kind) {
    case "story-post":
      return <PostStory x={x} />;
    case "story-breaking":
      return <BreakingStory x={x} />;
    case "story-recap":
      return <RecapStory x={x} />;
    case "story-update":
      return <UpdateStory x={x} />;
    default:
      return <AbsoluteFill style={{ background: brand.colors.ink, color: "#fff", fontSize: 40, alignItems: "center", justifyContent: "center" }}>historia desconocida: {x.kind}</AbsoluteFill>;
  }
};

export const StoryCard: React.FC<TemplateProps> = ({ piece }) => (
  <FontGate>
    <StoryInner piece={piece} />
  </FontGate>
);

