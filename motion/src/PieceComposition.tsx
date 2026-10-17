import React from "react";
import type { CalculateMetadataFunction } from "remotion";
import { z } from "zod";
import { formats } from "./design/layout";
import { pieceSchema, type Piece } from "./schema/piece";
import { isStillTemplate } from "./templates/meta";
import { getTemplate } from "./templates/registry";

export const FPS = 30;

export const compositionSchema = z.object({ piece: pieceSchema });
export type CompositionProps = z.infer<typeof compositionSchema>;

/** Composicion unica: despacha a la plantilla elegida en la presentacion. */
export const PieceComposition: React.FC<CompositionProps> = ({ piece }) => {
  const def = getTemplate(piece.presentation.template);
  const Component = def.component;
  return <Component piece={piece} />;
};

/** Duracion efectiva: la de la presentacion, acotada por el video si lo hay. */
export const pieceDurationInFrames = (piece: Piece, fps = FPS): number => {
  if (isStillTemplate(piece.presentation.template)) return 1;
  let seconds = piece.presentation.durationSeconds;
  const video = piece.content.videos[0];
  if (video?.durationSeconds) {
    seconds = Math.min(seconds, Math.max(5, video.durationSeconds - (video.trimStartSeconds ?? 0)));
  }
  return Math.max(1, Math.round(seconds * fps));
};

export const pieceDimensions = (piece: Piece) => formats[piece.presentation.format];

export const calculatePieceMetadata: CalculateMetadataFunction<CompositionProps> = ({ props }) => {
  const piece = pieceSchema.parse(props.piece);
  const { width, height } = pieceDimensions(piece);
  return {
    props: { piece },
    width,
    height,
    fps: FPS,
    durationInFrames: pieceDurationInFrames(piece),
    defaultOutName: `${piece.content.id}-${piece.presentation.template}-${piece.presentation.format}`,
  };
};
