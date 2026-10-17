import React, { useMemo } from "react";
import { AbsoluteFill, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { brand } from "../brand/brand.config";
import { getCategory } from "../brand/categories";
import { BrandLogo, DemoBadge, MetaLine } from "../components/brand";
import { FontGate } from "../components/FontGate";
import { getLayout, type Layout } from "../design/layout";
import { roleStyle, textRoles, upper } from "../design/tokens";
import { MaskWipe, Rise } from "../engine/animations/primitives";
import { slashCorner } from "../engine/animations/geometry";
import { resolveHook } from "../engine/hooks/registry";
import type { HookDefinition } from "../engine/hooks/types";
import { planTimeline, type TimelinePlan } from "../engine/timeline";
import { AnimationContext, DEFAULT_ANIMATION, ramp, sec } from "../engine/timing";
import type { Content, Piece, Presentation, TemplateId } from "../schema/piece";

export type TemplateProps = { piece: Piece };

export type TemplateSetup = {
  content: Content;
  presentation: Presentation;
  layout: Layout;
  accent: string;
  plan: TimelinePlan;
  hook: HookDefinition;
  videoLed: boolean;
};

export const OUTRO_SECONDS = 2.1;

export const useTemplateSetup = (piece: Piece, template: TemplateId): TemplateSetup => {
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const { content, presentation } = piece;
  const layout = getLayout(presentation.format, width, height);
  const accent = presentation.accent || (template === "breaking" ? brand.colors.accent : getCategory(content.category).accent);
  const hook = resolveHook(presentation.hook, content, template);
  const videoLed = content.videos.length > 0;
  const plan = useMemo(
    () =>
      planTimeline({
        content,
        template,
        fps,
        totalFrames: durationInFrames,
        hookSeconds: hook.seconds,
        outroSeconds: OUTRO_SECONDS,
        videoLed,
        skipFirstStat: hook.id === "data",
      }),
    [content, template, fps, durationInFrames, hook.seconds, hook.id, videoLed],
  );
  return { content, presentation, layout, accent, plan, hook, videoLed };
};

/** Contexto comun: tipografias listas + configuracion de animacion. */
export const PieceShell: React.FC<{ piece: Piece; children: React.ReactNode }> = ({ piece, children }) => (
  <FontGate>
    <AnimationContext.Provider value={{ ...DEFAULT_ANIMATION, ...piece.presentation.animation }}>
      <AbsoluteFill style={{ background: brand.colors.ink, overflow: "hidden" }}>{children}</AbsoluteFill>
    </AnimationContext.Provider>
  </FontGate>
);

export const DemoMark: React.FC<{ content: Content; layout: Layout }> = ({ content, layout }) =>
  content.isDemo ? <DemoBadge fontSize={Math.round(20 * layout.u)} top={Math.round(layout.safeTop * 0.32)} right={layout.margin} /> : null;

/**
 * CIERRE breve y reconocible (2 s): barrida diagonal de marca, logo, invitacion
 * y fuente. Sin intro larga del medio en ningun template.
 */
export const EndCard: React.FC<{
  content: Content;
  layout: Layout;
  accent: string;
  background?: string;
}> = ({ content, layout, accent, background = brand.colors.primary }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const cornerP = ramp(frame, sec(0.12, fps), sec(0.6, fps), "snap");
  const logoH = Math.round(124 * layout.u);
  return (
    <MaskWipe duration={0.5} easing="snap">
      <AbsoluteFill style={{ background }}>
        {/* Esquinas ambar: la firma de la plantilla original de Duo */}
        <AbsoluteFill style={{ background: brand.colors.accent, clipPath: slashCorner(cornerP, width, height, "top-left", 0.3) }} />
        <AbsoluteFill style={{ background: brand.colors.accent, clipPath: slashCorner(cornerP, width, height, "bottom-right", 0.34) }} />
        <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", gap: 34 * layout.u, paddingBottom: layout.format === "reel" ? 120 * layout.u : 0 }}>
          <Rise delay={0.22} distance={30}>
            <BrandLogo height={logoH} />
          </Rise>
          <Rise delay={0.4} distance={20}>
            <div style={{ display: "flex", alignItems: "center", gap: 18 * layout.u }}>
              <span style={{ ...roleStyle(textRoles.kicker, layout.type.kicker), color: brand.colors.accent }}>{upper(brand.copy.closingCta)}</span>
              <span style={{ ...roleStyle(textRoles.meta, layout.type.kicker), color: brand.colors.white }}>{brand.handle}</span>
            </div>
          </Rise>
        </AbsoluteFill>
        <div style={{ position: "absolute", left: layout.margin, right: layout.margin, bottom: layout.format === "reel" ? layout.safeBottom - 40 * layout.u : layout.margin, display: "flex", justifyContent: "center" }}>
          <Rise delay={0.55} distance={12}>
            <MetaLine source={content.source.name} date={content.date} fontSize={layout.type.meta} color="rgba(255,255,255,0.78)" />
          </Rise>
        </div>
      </AbsoluteFill>
    </MaskWipe>
  );
};

/** Monta el gancho resuelto encima del escenario. */
export const HookLayer: React.FC<{ setup: TemplateSetup; template: TemplateId }> = ({ setup, template }) => {
  const { hook, plan } = setup;
  const Overlay = hook.Overlay;
  return (
    <Sequence durationInFrames={plan.hook.duration + Math.round(plan.hook.duration * 1.5)} name={`Gancho: ${hook.label}`}>
      <Overlay content={setup.content} layout={setup.layout} accent={setup.accent} template={template} durationFrames={plan.hook.duration} />
    </Sequence>
  );
};
