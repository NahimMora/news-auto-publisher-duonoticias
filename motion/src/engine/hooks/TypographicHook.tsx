import React, { useMemo } from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { brand } from "../../brand/brand.config";
import { getCategory } from "../../brand/categories";
import { fitTextBlock, tokenize } from "../../design/textLayout";
import { roleStyle, textRoles, upper } from "../../design/tokens";
import { slashCorner } from "../animations/geometry";
import { BreakingLabel } from "../../components/brand";
import { MaskWipe } from "../animations/primitives";
import { TextReveal } from "../animations/TextReveal";
import { ramp, sec, useAnimationConfig } from "../timing";
import type { HookDefinition, HookProps } from "./types";

/** Palabras clave del gancho: el enfasis del titular o sus primeras palabras. */
export const hookKeywords = (headline: string): string => {
  const tokens = tokenize(headline);
  const emphasized = tokens.filter((t) => t.emphasis).map((t) => t.text);
  if (emphasized.length) return emphasized.slice(0, 3).join(" ");
  const words: string[] = [];
  for (const t of tokens) {
    words.push(t.text);
    const joined = words.join(" ");
    if (words.length >= 3 || (joined.length >= 10 && words.length >= 2)) break;
  }
  return words.join(" ").replace(/[,:;.]+$/, "");
};

/**
 * HOOK 1 · IMPACTO TIPOGRAFICO. La palabra clave golpea a cuerpo maximo sobre
 * un campo de color plano, cruzada por la diagonal de la marca; al final una
 * barrida diagonal retira el campo y revela la escena. Para urgencias y notas
 * sin imagen fuerte.
 */
const TypographicOverlay: React.FC<HookProps> = ({ content, layout, accent, template, durationFrames }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const cfg = useAnimationConfig();
  const breaking = template === "breaking" || content.breaking;
  const field = breaking ? accent : brand.colors.primary;
  const ink = breaking ? brand.colors.ink : brand.colors.white;
  const corner = breaking ? brand.colors.primary : accent;
  const keyword = hookKeywords(content.headline);
  const role = { ...textRoles.dataNumber, uppercase: true, lineHeight: 0.92 };
  const maxW = width - layout.margin * 2;
  const block = useMemo(
    () =>
      fitTextBlock({
        text: keyword,
        role,
        maxWidth: maxW,
        maxLines: 3,
        minSize: Math.round(140 * layout.u),
        maxSize: Math.round((layout.format === "reel" ? 380 : 300) * layout.u),
        maxHeight: height * 0.5,
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [keyword, maxW, layout.u, layout.format, height],
  );
  const exitStart = durationFrames - sec(0.42, fps, cfg.speed);
  // Respiracion de escala durante todo el gancho (camara que se acerca).
  const breathe = interpolate(frame, [0, durationFrames], [1.06, 1], { extrapolateRight: "clamp" });
  // Esquinas de la marca (como la plantilla original) entrando en diagonal.
  const cornerP = ramp(frame, -sec(0.22, fps, cfg.speed), sec(0.55, fps, cfg.speed), "snap");
  const echoX = interpolate(frame, [0, durationFrames], [0, -width * 0.22]);
  const top = height * 0.52 - block.height / 2;

  return (
    <MaskWipe mode="out" delay={exitStart / fps} duration={0.42} easing="exit">
      <AbsoluteFill style={{ background: field, overflow: "hidden" }}>
        {/* Eco tipografico en contorno: profundidad sin ruido */}
        <div
          style={{
            position: "absolute",
            left: layout.margin,
            top: top - block.fontSize * 1.25,
            translate: `${echoX}px 0`,
            ...roleStyle(role, block.fontSize * 2.3),
            color: "transparent",
            WebkitTextStroke: `${Math.max(2, 3 * layout.u)}px ${ink}`,
            opacity: 0.14,
          }}
        >
          {upper(keyword)}
        </div>
        <AbsoluteFill style={{ background: corner, clipPath: slashCorner(cornerP, width, height, "top-left", 0.26) }} />
        <AbsoluteFill style={{ background: corner, clipPath: slashCorner(cornerP, width, height, "bottom-right", 0.3) }} />
        {breaking ? (
          <div style={{ position: "absolute", left: layout.margin, top: layout.safeTop }}>
            <BreakingLabel fontSize={layout.type.kicker} delay={0} />
          </div>
        ) : (
          <div style={{ position: "absolute", left: layout.margin, top: top - layout.type.kicker * 2.4 }}>
            <span style={{ ...roleStyle(textRoles.kicker, layout.type.kicker), color: ink }}>{upper(getCategory(content.category).label)}</span>
          </div>
        )}
        <div style={{ position: "absolute", left: layout.margin, top, width: maxW, scale: String(breathe), transformOrigin: "left center" }}>
          <TextReveal layout={block} role={role} color={ink} accent={ink} mode="word" stagger={0.07} duration={0.42} easing="punch" delay={-0.16} />
          <div style={{ marginTop: block.fontSize * 0.16, display: "flex", alignItems: "center", gap: 18 * layout.u, opacity: ramp(frame, sec(0.2, fps, cfg.speed), sec(0.3, fps, cfg.speed), "snap") }}>
            <div style={{ width: 64 * layout.u, height: Math.max(3, 6 * layout.u), background: ink }} />
            <span style={{ ...roleStyle(textRoles.meta, layout.type.meta * 1.15), color: ink }}>{upper(content.location ?? getCategory(content.category).label)}</span>
          </div>
        </div>
      </AbsoluteFill>
    </MaskWipe>
  );
};

export const typographicHook: HookDefinition = {
  id: "typographic",
  label: "Impacto tipográfico",
  description: "La palabra clave golpea a cuerpo máximo y una barrida diagonal revela la noticia.",
  seconds: 1.5,
  Overlay: TypographicOverlay,
  suits: (content, template) => (template === "breaking" || content.breaking ? 0.9 : content.photos.length + content.videos.length === 0 ? 0.8 : 0.35),
};
