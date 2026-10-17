import React from "react";
import { AbsoluteFill, interpolate, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { brand } from "../brand/brand.config";
import type { Layout } from "../design/layout";
import { CinematicZoom, MaskWipe, ParallaxLayer } from "../engine/animations/primitives";
import type { TimelinePlan } from "../engine/timeline";
import { springAt, useAnimationConfig } from "../engine/timing";
import type { Content } from "../schema/piece";
import { framingFor, PhotoLayer, VideoLayer, WindowedPhoto } from "./media";

/** El video en ventana conserva casi todo el cuadro: fundido mas corto. */
const WINDOW_FADE_SOFT: React.CSSProperties = {
  maskImage: "linear-gradient(to bottom, transparent 0%, #000 6%, #000 94%, transparent 100%)",
  WebkitMaskImage: "linear-gradient(to bottom, transparent 0%, #000 6%, #000 94%, transparent 100%)",
};
import { Grain } from "./brand";

export type StageCut = "punch" | "slash";

type Props = {
  content: Content;
  plan: TimelinePlan;
  layout: Layout;
  cut: StageCut;
  accent: string;
  /** Centro vertical (0..1) de la ventana cuando la foto/video no llena el cuadro. */
  windowCenter?: number;
  /**
   * Rectangulo a llenar cuando la imagen no cubre el cuadro: la imagen se
   * escala para cubrirlo recortando como mucho MAX_WINDOW_CROP de su ancho.
   */
  windowRect?: { top: number; height: number };
  /**
   * Alejamiento de camara: la imagen en ventana arranca a pantalla completa y
   * se retrae a su rectangulo desde `startFrame` (sincronizado con el panel).
   */
  windowIntro?: { startFrame: number };
  /** Fondo cuando no hay ninguna imagen. */
  emptyBackground?: string;
};

/** Recorte lateral maximo tolerado al agrandar una imagen apaisada. */
const MAX_WINDOW_CROP = 0.3;

/** Geometria de la ventana: alto/top del area visible de la imagen. */
const windowGeometry = (
  media: { width?: number; height?: number },
  frameW: number,
  frameH: number,
  center: number,
  minTop: number,
  rect?: { top: number; height: number },
) => {
  const aspect = media.width && media.height ? media.width / media.height : 16 / 9;
  const natural = frameW / aspect;
  if (!rect) {
    return { top: Math.max(minTop, frameH * center - natural / 2), height: natural };
  }
  const maxH = natural / (1 - MAX_WINDOW_CROP);
  const h = Math.min(rect.height, maxH);
  return { top: rect.top + (rect.height - h) / 2, height: h };
};

/**
 * Escenario persistente: la foto o el video corre debajo de todas las escenas
 * con camara virtual continua. Las escenas de texto se montan encima. Cambia
 * de foto en cada bloque (corte seco con destello o barrida diagonal).
 */
export const MediaStage: React.FC<Props> = ({ content, plan, layout, cut, accent, windowCenter = 0.4, windowRect, windowIntro, emptyBackground }) => {
  const { width, height, fps } = useVideoConfig();
  const frame = useCurrentFrame();
  // 0 = pantalla completa, 1 = ventana final.
  const introP = windowIntro ? springAt(frame, fps, windowIntro.startFrame, { stiffness: 110, damping: 20 }) : 1;
  const withIntro = (g: { top: number; height: number }) =>
    introP >= 1 ? g : { top: interpolate(introP, [0, 1], [0, g.top]), height: interpolate(introP, [0, 1], [height, g.height]) };
  const cfg = useAnimationConfig();
  const video = content.videos[0];

  if (video) {
    const framing = framingFor(video, width, height);
    if (framing === "cover") {
      return (
        <AbsoluteFill style={{ background: brand.colors.ink }}>
          <CinematicZoom from={1.02} to={1 + (cfg.cameraZoom - 1) * 0.5}>
            <VideoLayer clip={video} />
          </CinematicZoom>
        </AbsoluteFill>
      );
    }
    const { top, height: vh } = withIntro(windowGeometry(video, width, height, windowCenter, layout.safeTop, windowRect));
    return (
      <AbsoluteFill style={{ background: brand.colors.primaryDeep }}>
        <StagePattern accent={accent} />
        <div style={{ position: "absolute", left: 0, right: 0, top, height: vh, overflow: "hidden", ...WINDOW_FADE_SOFT }}>
          <CinematicZoom from={1} to={1 + (cfg.cameraZoom - 1) * 0.4}>
            <VideoLayer clip={video} />
          </CinematicZoom>
        </div>
        <Grain opacity={0.08} />
      </AbsoluteFill>
    );
  }

  if (content.photos.length === 0) {
    return (
      <AbsoluteFill style={{ background: emptyBackground ?? brand.colors.primaryDeep }}>
        <StagePattern accent={accent} />
        <Grain opacity={0.08} />
      </AbsoluteFill>
    );
  }

  // Segmentos: el primero arranca en 0 (incluye el gancho).
  const segments = plan.beats.map((b, i) => ({
    start: i === 0 ? 0 : b.start,
    end: i === plan.beats.length - 1 ? plan.total : plan.beats[i + 1].start,
    photoIndex: b.photoIndex,
  }));
  const overlap = cut === "slash" ? Math.round(0.6 * fps) : 0;
  const singlePhoto = content.photos.length === 1;

  return (
    <AbsoluteFill style={{ background: brand.colors.ink }}>
      {segments.map((seg, i) => {
        const photo = content.photos[seg.photoIndex] ?? content.photos[0];
        const framing = framingFor(photo, width, height);
        const duration = seg.end - seg.start + overlap;
        // Con una sola foto se alternan encuadres: abierto / cerrado.
        const tight = singlePhoto && i % 2 === 1;
        const zoomFrom = tight ? 1.26 : 1.0;
        const zoomTo = tight ? 1.34 : cfg.cameraZoom;
        const focus = photo.focus ?? { x: 0.5, y: 0.42 };
        const g = windowGeometry(photo, width, height, windowCenter, layout.safeTop * 0.6, windowRect);
        const { top, height: vh } = i === 0 ? withIntro(g) : g;
        const body =
          framing === "cover" ? (
            <CinematicZoom from={zoomFrom} to={zoomTo} focus={focus} durationFrames={duration} drift={i % 2 ? -40 : 40}>
              <PhotoLayer photo={photo} />
            </CinematicZoom>
          ) : (
            <ParallaxLayer depth={0.6} distance={90} direction={i % 2 ? "right" : "left"} durationFrames={duration}>
              <CinematicZoom from={1} to={1.06} focus={focus} durationFrames={duration}>
                <WindowedPhoto photo={photo} top={top} height={vh} />
              </CinematicZoom>
            </ParallaxLayer>
          );
        return (
          <Sequence key={i} from={seg.start} durationInFrames={duration} name={`Foto ${i + 1}`}>
            {cut === "slash" && i > 0 ? <MaskWipe duration={0.6}>{body}</MaskWipe> : <AbsoluteFill>{body}</AbsoluteFill>}
            {cut === "punch" && i > 0 ? <CutFlash color={accent} /> : null}
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};

/** Destello de 2 frames en el corte (urgencia). */
const CutFlash: React.FC<{ color: string }> = ({ color }) => {
  const frame = useCurrentFrame();
  if (frame > 2) return null;
  return <AbsoluteFill style={{ background: frame === 0 ? color : brand.colors.white, opacity: frame === 0 ? 0.92 : 0.35 }} />;
};

/**
 * Fondo grafico cuando la imagen no llena el cuadro: diagonales finas en la
 * pendiente de la marca, en movimiento lento. Sin gradientes decorativos.
 */
export const StagePattern: React.FC<{ accent: string; opacity?: number }> = ({ accent, opacity = 0.12 }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const offset = (frame * 0.6) % 120;
  return (
    <AbsoluteFill style={{ opacity }}>
      <svg width={width} height={height} style={{ position: "absolute", inset: 0 }}>
        <defs>
          <pattern id="duo-slash" width="120" height="120" patternUnits="userSpaceOnUse" patternTransform={`rotate(-36) translate(${offset} 0)`}>
            <rect x="0" y="0" width="6" height="120" fill={accent} />
          </pattern>
        </defs>
        <rect width={width} height={height} fill="url(#duo-slash)" />
      </svg>
    </AbsoluteFill>
  );
};
