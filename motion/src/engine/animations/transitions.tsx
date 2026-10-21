import React from "react";
import type { TransitionPresentation, TransitionPresentationComponentProps } from "@remotion/transitions";
import { AbsoluteFill, useVideoConfig } from "remotion";
import { slashBand, slashClip } from "./geometry";

/**
 * SCENE TRANSITIONS para TransitionSeries. Firmas de la marca:
 * - brandSlash: la escena nueva entra por una barrida diagonal con un filo de
 *   color (ambar por defecto). Editorial y data.
 * - punchCut: corte seco con un destello de color de 2-3 frames y un leve
 *   empuje de escala. Urgencia.
 */

type SlashProps = { color: string; thickness: number; from: "left" | "right" };

const SlashPresentation: React.FC<TransitionPresentationComponentProps<SlashProps>> = ({
  children,
  presentationDirection,
  presentationProgress,
  passedProps,
}) => {
  const { width, height } = useVideoConfig();
  if (presentationDirection === "exiting") {
    return <AbsoluteFill>{children}</AbsoluteFill>;
  }
  const p = presentationProgress;
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ clipPath: p >= 1 ? undefined : slashClip(p, width, height, passedProps.from) }}>{children}</AbsoluteFill>
      {p > 0 && p < 1 ? (
        <AbsoluteFill
          style={{
            background: passedProps.color,
            clipPath: slashBand(passedProps.from === "right" ? 1 - p : p, width, height, passedProps.thickness),
          }}
        />
      ) : null}
    </AbsoluteFill>
  );
};

export const brandSlash = (props: Partial<SlashProps> = {}): TransitionPresentation<SlashProps> => ({
  component: SlashPresentation,
  props: { color: props.color ?? "#FFB700", thickness: props.thickness ?? 90, from: props.from ?? "left" },
});

type PunchProps = { color: string };

const PunchPresentation: React.FC<TransitionPresentationComponentProps<PunchProps>> = ({
  children,
  presentationDirection,
  presentationProgress,
  passedProps,
}) => {
  const p = presentationProgress;
  if (presentationDirection === "exiting") {
    return <AbsoluteFill style={{ opacity: p < 0.5 ? 1 : 0 }}>{children}</AbsoluteFill>;
  }
  const flash = p > 0.35 && p < 0.65;
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ opacity: p >= 0.5 ? 1 : 0, scale: String(1 + (1 - p) * 0.08) }}>{children}</AbsoluteFill>
      {flash ? <AbsoluteFill style={{ background: passedProps.color }} /> : null}
    </AbsoluteFill>
  );
};

export const punchCut = (props: Partial<PunchProps> = {}): TransitionPresentation<PunchProps> => ({
  component: PunchPresentation,
  props: { color: props.color ?? "#FFB700" },
});
