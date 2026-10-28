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

type RecapItem = { headline: string; photo?: string; views?: number; category?: string };

const Views: React.FC<{ n?: number; size: number }> = ({ n, size }) =>
  n ? <span style={{ ...roleStyle(textRoles.meta, size), color: "rgba(255,255,255,0.75)" }}>👁 {fmtNum(n)} VISTAS</span> : null;

const clean = (text: string) => text.replace(/\*/g, "");

const RecapStory: React.FC<{ x: Extra }> = ({ x }) => {
  const { width: W } = useVideoConfig();
  const u = W / 1080;
  const m = Math.round(64 * u);
  const items = (x.items as RecapItem[]) ?? [];
  const [first, ...rest] = items;
  const rowH = Math.round(150 * u);
  const firstCat = getCategory(first?.category);
  return (
    <BrandFrame corners={0.07}>
      <Head u={u} m={m} label="Lo más importante del día" />
      <div style={{ position: "absolute", left: m, right: m, top: (TOP + 84) * u, bottom: (1920 - BOTTOM + 70) * u, display: "flex", flexDirection: "column", gap: 18 * u }}>
        <span style={{ ...roleStyle(textRoles.meta, Math.round(24 * u)), color: "rgba(255,255,255,0.8)" }}>{upper(String(x.dateLabel ?? ""))}</span>
        {first ? (
          <div style={{ position: "relative", flex: 1, minHeight: 420 * u, overflow: "hidden", background: brand.colors.ink }}>
            <Photo src={first.photo} />
            <AbsoluteFill style={{ background: "linear-gradient(to bottom, rgba(12,8,18,0) 30%, rgba(12,8,18,0.92) 82%)" }} />
            <div style={{ position: "absolute", left: 0, top: 0, padding: `${6 * u}px ${22 * u}px`, background: brand.colors.accent }}>
              <span style={{ ...roleStyle(textRoles.dataNumber, Math.round(84 * u)), color: brand.colors.ink }}>1</span>
            </div>
            <div style={{ position: "absolute", left: 28 * u, right: 28 * u, bottom: 26 * u, display: "flex", flexDirection: "column", gap: 12 * u }}>
              <span style={{ ...roleStyle(textRoles.kicker, Math.round(22 * u)), color: firstCat.accent }}>{upper(firstCat.label)} · LA MÁS VISTA</span>
              <T role={textRoles.postHeadline} size={Math.round(54 * u)} lines={3}>
                {clean(first.headline)}
              </T>
              <Views n={first.views} size={Math.round(21 * u)} />
            </div>
          </div>
        ) : null}
        {rest.map((it, i) => {
          const cat = getCategory(it.category);
          return (
            <div key={i} style={{ display: "flex", gap: 22 * u, height: rowH, flex: "none", alignItems: "center", background: "rgba(255,255,255,0.07)" }}>
              <div style={{ position: "relative", width: rowH, height: rowH, flex: "none", overflow: "hidden" }}>
                <Photo src={it.photo} />
                <AbsoluteFill style={{ background: "linear-gradient(135deg, rgba(12,8,18,0.8) 0%, rgba(12,8,18,0) 55%)" }} />
                <span style={{ ...roleStyle(textRoles.dataNumber, Math.round(64 * u)), color: brand.colors.accent, position: "absolute", left: 12 * u, top: 4 * u }}>{i + 2}</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 * u, paddingRight: 22 * u, minWidth: 0 }}>
                <T role={textRoles.deckStrong} size={Math.round(30 * u)} lines={2}>
                  {clean(it.headline)}
                </T>
                <div style={{ display: "flex", gap: 18 * u, alignItems: "center" }}>
                  <span style={{ ...roleStyle(textRoles.kicker, Math.round(18 * u)), color: cat.accent }}>{upper(cat.label)}</span>
                  <Views n={it.views} size={Math.round(18 * u)} />
                </div>
              </div>
            </div>
          );
        })}
      </div>
      <div style={{ position: "absolute", left: m, right: m, top: (BOTTOM - 40) * u, display: "flex", justifyContent: "center" }}>
        <span style={{ ...roleStyle(textRoles.kicker, Math.round(24 * u)), color: brand.colors.accent }}>TODAS LAS NOTAS EN {upper(brand.handle)}</span>
      </div>
    </BrandFrame>
  );
};

type Fact = { value: string; label: string; time: string; source: string };

/**
 * Noticia en desarrollo como linea de tiempo: arriba la foto (ocupa el alto que
 * sobra), abajo "lo nuevo" con su hora, la cifra que cambio o lo que se sabe, y
 * "lo que publicamos antes" para que se entienda que es una actualizacion.
 */
const UpdateStory: React.FC<{ x: Extra }> = ({ x }) => {
  const { width: W } = useVideoConfig();
  const u = W / 1080;
  const m = Math.round(70 * u);
  const before = x.before as Fact | undefined;
  const after = x.after as Fact | undefined;
  const previous = x.previous as { headline: string; time: string } | undefined;
  const points = ((x.points as string[]) ?? []).slice(0, before && after ? 0 : 3);
  const timeLabel = after?.time ?? String(x.timeLabel ?? "");
  const block = useHeadline(String(x.headline ?? ""), W - m * 2 - 50 * u, Math.round(54 * u), Math.round(80 * u), 330 * u, 4);
  const dot = (filled: boolean) => (
    <div style={{ width: 26 * u, height: 26 * u, borderRadius: "50%", flex: "none", marginTop: 6 * u, background: filled ? brand.colors.accent : brand.colors.primaryDeep, border: `${5 * u}px solid ${filled ? brand.colors.accent : "rgba(255,255,255,0.5)"}` }} />
  );
  return (
    <BrandFrame corners={0.07}>
      <Head u={u} m={m} label={brand.copy.developingLabel} color={brand.colors.accent} />
      <div style={{ position: "absolute", left: m, right: m, top: (TOP + 100) * u, bottom: (1920 - BOTTOM + 100) * u, display: "flex", flexDirection: "column", gap: 44 * u }}>
        <div style={{ position: "relative", height: 500 * u, flexShrink: 1, minHeight: 260 * u, overflow: "hidden", background: brand.colors.ink }}>
          <Photo src={x.photo as string} />
          <AbsoluteFill style={{ background: "linear-gradient(to bottom, rgba(12,8,18,0) 55%, rgba(12,8,18,0.7) 100%)" }} />
          {x.location ? (
            <span style={{ ...roleStyle(textRoles.kicker, Math.round(24 * u)), color: brand.colors.white, position: "absolute", left: 24 * u, bottom: 20 * u }}>📍 {upper(String(x.location))}</span>
          ) : null}
        </div>
        <div style={{ display: "flex", gap: 28 * u, flex: 1 }}>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", flex: "none" }}>
            {dot(true)}
            {previous ? <div style={{ flex: 1, width: 5 * u, background: "rgba(255,255,255,0.3)" }} /> : null}
            {previous ? dot(false) : null}
          </div>
          <div style={{ display: "flex", flexDirection: "column", justifyContent: "space-between", gap: 30 * u, minWidth: 0, flex: 1 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 22 * u }}>
              <span style={{ ...roleStyle(textRoles.kicker, Math.round(28 * u)), color: brand.colors.accent }}>LO NUEVO{timeLabel ? ` · ${upper(timeLabel)}` : ""}</span>
              <TextReveal layout={block} role={textRoles.postHeadline} color={brand.colors.white} accent={brand.colors.accent} mode="none" emphasisStyle="marker" markerTextColor={brand.colors.ink} />
            </div>
            {before && after ? (
              <div style={{ display: "flex", alignItems: "center", gap: 22 * u, padding: `${18 * u}px ${24 * u}px`, background: "rgba(255,255,255,0.08)" }}>
                <span style={{ ...roleStyle(textRoles.dataNumber, Math.round(96 * u)), color: "rgba(255,255,255,0.45)", textDecoration: "line-through", textDecorationThickness: 5 * u }}>{before.value}</span>
                <svg width={46 * u} height={46 * u} viewBox="0 0 24 24">
                  <path d="M4 12h14M12 5l7 7-7 7" stroke={brand.colors.accent} strokeWidth="3" fill="none" />
                </svg>
                <span style={{ ...roleStyle(textRoles.dataNumber, Math.round(120 * u)), color: brand.colors.accent }}>{after.value}</span>
                <T role={textRoles.deckStrong} size={Math.round(34 * u)}>
                  {after.label}
                </T>
              </div>
            ) : null}
            {points.length ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 18 * u }}>
                {points.map((pt) => (
              <div key={pt} style={{ display: "flex", gap: 16 * u, alignItems: "flex-start" }}>
                <span style={{ width: 13 * u, height: 13 * u, background: brand.colors.accent, flex: "none", rotate: "45deg", marginTop: 14 * u }} />
                <T role={textRoles.deck} size={Math.round(30 * u)} color="rgba(255,255,255,0.9)" lines={2}>
                  {pt}
                </T>
              </div>
                ))}
              </div>
            ) : null}
            {previous ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 10 * u, paddingTop: 26 * u, borderTop: "1px solid rgba(255,255,255,0.16)" }}>
                <span style={{ ...roleStyle(textRoles.meta, Math.round(22 * u)), color: "rgba(255,255,255,0.65)" }}>LO QUE PUBLICAMOS ANTES{previous.time ? ` · ${upper(previous.time)}` : ""}</span>
                <T role={textRoles.deck} size={Math.round(28 * u)} color="rgba(255,255,255,0.65)" lines={2}>
                  {clean(previous.headline)}
                </T>
              </div>
            ) : null}
          </div>
        </div>
      </div>
      <div style={{ position: "absolute", left: m, right: m, top: (BOTTOM - 40) * u, display: "flex", justifyContent: "center" }}>
        <span style={{ ...roleStyle(textRoles.kicker, Math.round(24 * u)), color: brand.colors.white }}>SEGUIMOS LA COBERTURA EN {upper(brand.handle)}</span>
      </div>
    </BrandFrame>
  );
};

/**
 * Fondo descargable para compartir a mano un post o un reel en historias (2026-10-23): el marco de
 * "Nuevo en el feed" sin la nota. El centro queda libre para el sticker del post compartido.
 */
const ShareBackground: React.FC<{ x: Extra }> = ({ x }) => {
  const { width: W } = useVideoConfig();
  const u = W / 1080;
  const m = Math.round(70 * u);
  const reel = x.variant === "reel";
  return (
    <BrandFrame corners={0.12}>
      <Head u={u} m={m} label={reel ? "Nuevo reel" : "Nuevo en el feed"} />
      <div style={{ position: "absolute", left: m, right: m, top: (BOTTOM - 70) * u, display: "flex", flexDirection: "column", alignItems: "center", gap: 18 * u }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 * u, padding: `${18 * u}px ${30 * u}px`, background: brand.colors.white, borderRadius: 60 * u }}>
          <span style={{ ...roleStyle(textRoles.kicker, Math.round(28 * u)), color: brand.colors.ink }}>{reel ? "TOCÁ PARA VER EL REEL" : "TOCÁ PARA VER LA NOTA"}</span>
          <svg width={34 * u} height={34 * u} viewBox="0 0 24 24">
            <path d="M12 19V5M5 12l7-7 7 7" stroke={brand.colors.ink} strokeWidth="3" fill="none" />
          </svg>
        </div>
      </div>
    </BrandFrame>
  );
};

const StoryInner: React.FC<TemplateProps> = ({ piece }) => {
  const x = extraOf(piece.content);
  switch (x.kind) {
    case "story-share-bg":
      return <ShareBackground x={x} />;
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

