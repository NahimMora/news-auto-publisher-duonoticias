import React from "react";
import { AbsoluteFill, useVideoConfig } from "remotion";
import { brand } from "../../brand/brand.config";
import { getCategory } from "../../brand/categories";
import { fitSingleLine, fitTextBlock } from "../../design/textLayout";
import { roleStyle, textRoles, upper } from "../../design/tokens";
import { NumberCounter } from "../animations/editorial";
import { GrowBar, MaskWipe } from "../animations/primitives";
import { TextReveal } from "../animations/TextReveal";
import { sec, useAnimationConfig } from "../timing";
import type { HookDefinition, HookProps } from "./types";

/**
 * HOOK 3 · DATO PROTAGONISTA. La cifra principal cuenta a cuerpo gigante, una
 * regla de acento la subraya y aparece su etiqueta; luego la barrida diagonal
 * revela el contexto. Solo usa cifras que vienen en la nota (stats).
 */
const DataOverlay: React.FC<HookProps> = ({ content, layout, accent, durationFrames }) => {
  const { fps, width, height } = useVideoConfig();
  const cfg = useAnimationConfig();
  const stat = content.stats[0];
  if (!stat) return null;
  const exitStart = durationFrames - sec(0.42, fps, cfg.speed);
  const maxW = width - layout.margin * 2;
  const finalText = `${stat.prefix ?? ""}${formatStat(stat.value, stat.decimals)}${stat.unit && stat.unit.length <= 2 ? stat.unit : ""}`;
  const numberSize = fitSingleLine(finalText, textRoles.dataNumber, maxW * 0.96, Math.round(layout.type.data * 1.45));
  const labelLayout = fitTextBlock({
    text: stat.label,
    role: textRoles.deckStrong,
    maxWidth: maxW,
    maxLines: 3,
    preferLines: 2,
    minSize: Math.round(44 * layout.u),
    maxSize: Math.round(66 * layout.u),
  });
  const kickerSize = layout.type.kicker;
  const blockH = kickerSize * 2.2 + numberSize * 0.9 + 40 * layout.u + labelLayout.height;
  const top = height * 0.5 - blockH / 2;
  return (
    <MaskWipe mode="out" delay={exitStart / fps} duration={0.42} easing="exit">
      <AbsoluteFill style={{ background: brand.colors.primary }}>
        <div style={{ position: "absolute", left: layout.margin, top, width: maxW }}>
          <span style={{ ...roleStyle(textRoles.kicker, kickerSize), color: accent }}>{upper(`${getCategory(content.category).label} · en cifras`)}</span>
          <div style={{ marginTop: kickerSize * 0.9 }}>
            <NumberCounter
              value={stat.value}
              decimals={stat.decimals}
              prefix={stat.prefix}
              unit={stat.unit}
              fontSize={numberSize}
              color={brand.colors.white}
              unitColor={accent}
              duration={1.2}
              delay={-0.25}
            />
          </div>
          <GrowBar length={maxW * 0.3} thickness={Math.round(12 * layout.u)} color={accent} delay={0.3} duration={0.6} style={{ marginTop: numberSize * 0.04 }} />
          <div style={{ marginTop: 30 * layout.u }}>
            <TextReveal layout={labelLayout} role={textRoles.deckStrong} color={brand.colors.white} accent={accent} mode="line" delay={-0.1} />
          </div>
        </div>
      </AbsoluteFill>
    </MaskWipe>
  );
};

const formatStat = (v: number, decimals: number) =>
  new Intl.NumberFormat("es-AR", { minimumFractionDigits: decimals, maximumFractionDigits: decimals }).format(v);

export const dataHook: HookDefinition = {
  id: "data",
  label: "Dato protagonista",
  description: "La cifra principal cuenta a cuerpo gigante y revela el contexto de la noticia.",
  seconds: 2.1,
  Overlay: DataOverlay,
  suits: (content, template) => (content.stats.length === 0 ? 0 : template === "data" ? 1 : 0.5),
};
