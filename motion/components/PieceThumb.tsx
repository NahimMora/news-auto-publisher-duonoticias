"use client";

import { Thumbnail } from "@remotion/player";
import { useMemo } from "react";
import { PieceComposition, pieceDimensions, pieceDurationInFrames, FPS } from "../src/PieceComposition";
import { pieceSchema, type PieceInput } from "../src/schema/piece";
import { toPlayerPiece } from "../lib/client/api";

/** Miniatura real (render en vivo del frame elegido) de una pieza. */
export const PieceThumb: React.FC<{ piece: PieceInput; frameSeconds?: number; className?: string }> = ({ piece, frameSeconds = 3, className }) => {
  const parsed = useMemo(() => pieceSchema.safeParse(piece), [piece]);
  if (!parsed.success) return <div className={`grid place-items-center bg-raised text-xs text-mute ${className ?? ""}`}>Pieza inválida</div>;
  const p = toPlayerPiece(parsed.data);
  const { width, height } = pieceDimensions(p);
  const duration = pieceDurationInFrames(p);
  return (
    <div className={className} style={{ aspectRatio: `${width} / ${height}` }}>
      <Thumbnail
        component={PieceComposition}
        inputProps={{ piece: p }}
        compositionWidth={width}
        compositionHeight={height}
        durationInFrames={duration}
        fps={FPS}
        frameToDisplay={Math.min(duration - 1, Math.round(frameSeconds * FPS))}
        style={{ width: "100%", height: "100%" }}
      />
    </div>
  );
};
