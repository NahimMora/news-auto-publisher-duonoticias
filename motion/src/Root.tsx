import React from "react";
import { Composition, Folder } from "remotion";
import { demos } from "./demo/pieces";
import { calculatePieceMetadata, compositionSchema, FPS, PieceComposition, type CompositionProps } from "./PieceComposition";
import { pieceSchema } from "./schema/piece";

const demo = (input: unknown): CompositionProps => ({ piece: pieceSchema.parse(input) });

export const RemotionRoot: React.FC = () => {
  return (
    <>
      {/* Composicion generica: la usan el renderer del pipeline y el panel. */}
      <Composition
        id="Piece"
        component={PieceComposition}
        schema={compositionSchema}
        calculateMetadata={calculatePieceMetadata}
        durationInFrames={450}
        fps={FPS}
        width={1080}
        height={1920}
        defaultProps={demo(demos.breaking)}
      />
      <Folder name="Demos">
        <Composition
          id="Demo-Breaking-Reel"
          component={PieceComposition}
          schema={compositionSchema}
          calculateMetadata={calculatePieceMetadata}
          durationInFrames={450}
          fps={FPS}
          width={1080}
          height={1920}
          defaultProps={demo(demos.breaking)}
        />
        <Composition
          id="Demo-Editorial-Reel"
          component={PieceComposition}
          schema={compositionSchema}
          calculateMetadata={calculatePieceMetadata}
          durationInFrames={450}
          fps={FPS}
          width={1080}
          height={1920}
          defaultProps={demo(demos.editorial)}
        />
        <Composition
          id="Demo-Data-Reel"
          component={PieceComposition}
          schema={compositionSchema}
          calculateMetadata={calculatePieceMetadata}
          durationInFrames={480}
          fps={FPS}
          width={1080}
          height={1920}
          defaultProps={demo(demos.data)}
        />
        <Composition
          id="Demo-Static-Portrait"
          component={PieceComposition}
          schema={compositionSchema}
          calculateMetadata={calculatePieceMetadata}
          durationInFrames={1}
          fps={FPS}
          width={1080}
          height={1350}
          defaultProps={demo(demos.staticPortrait)}
        />
        <Composition
          id="Demo-Static-Square"
          component={PieceComposition}
          schema={compositionSchema}
          calculateMetadata={calculatePieceMetadata}
          durationInFrames={1}
          fps={FPS}
          width={1080}
          height={1080}
          defaultProps={demo(demos.staticSquare)}
        />
        <Composition
          id="Demo-Static-Type"
          component={PieceComposition}
          schema={compositionSchema}
          calculateMetadata={calculatePieceMetadata}
          durationInFrames={1}
          fps={FPS}
          width={1080}
          height={1350}
          defaultProps={demo(demos.staticType)}
        />
      </Folder>
    </>
  );
};
