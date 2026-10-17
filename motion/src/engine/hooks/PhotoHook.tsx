import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { brand } from "../../brand/brand.config";
import { getCategory } from "../../brand/categories";
import { slitEdges } from "../animations/geometry";
import { LocationTag } from "../animations/editorial";
import { ramp, sec, useAnimationConfig } from "../timing";
import type { HookDefinition, HookProps } from "./types";

/** Segundos de ventaja: en el frame 0 la ranura ya muestra imagen. */
export const REVEAL_LEAD = 0.16;

/**
 * HOOK 2 · REVELACION FOTOGRAFICA. La imagen se abre por una ranura diagonal
 * desde el centro mientras la camara se asienta; el filo de la ranura brilla
 * con el acento y la ubicacion cae sobre la foto. El template envuelve el
 * escenario con el mismo recorte (revealsStage). Para notas con buena imagen.
 */
const PhotoOverlay: React.FC<HookProps> = ({ content, layout, accent, durationFrames }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const cfg = useAnimationConfig();
  // Mismo tiempo que el ImageReveal del template (arranca ya abierto un poco).
  const p = ramp(frame, -sec(REVEAL_LEAD, fps, cfg.speed), sec(0.95, fps, cfg.speed), "snap");
  const edgeOpacity = 1 - ramp(frame, sec(0.55, fps, cfg.speed), sec(0.3, fps, cfg.speed), "glide");
  const location = content.location ?? getCategory(content.category).label;
  const [left, right] = slitEdges(p, width, height, 16 * layout.u);
  return (
    <AbsoluteFill>
      {/* Filos luminosos de la ranura */}
      {p < 1 ? (
        <>
          <AbsoluteFill style={{ background: accent, clipPath: left, opacity: edgeOpacity }} />
          <AbsoluteFill style={{ background: accent, clipPath: right, opacity: edgeOpacity }} />
        </>
      ) : null}
      <div style={{ position: "absolute", left: layout.margin, top: layout.safeTop + layout.type.meta * 2.2 }}>
        <LocationTag
          text={location}
          fontSize={layout.type.meta * 1.12}
          color={brand.colors.white}
          pinColor={accent}
          delay={0.3}
          exitAt={durationFrames - sec(0.3, fps, cfg.speed)}
        />
      </div>
    </AbsoluteFill>
  );
};

export const photoHook: HookDefinition = {
  id: "photo",
  label: "Revelación fotográfica",
  description: "La foto o el video se abre por una ranura diagonal con movimiento de cámara.",
  seconds: 1.3,
  Overlay: PhotoOverlay,
  revealsStage: true,
  suits: (content, template) => (content.photos.length + content.videos.length > 0 ? (template === "editorial" ? 0.9 : 0.6) : 0),
};
