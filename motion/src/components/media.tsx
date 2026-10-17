import React from "react";
import { Video } from "@remotion/media";
import { AbsoluteFill, Img, staticFile, useVideoConfig } from "remotion";
import type { z } from "zod";
import type { mediaPhotoSchema, mediaVideoSchema } from "../schema/piece";

export type Photo = z.infer<typeof mediaPhotoSchema>;
export type VideoClip = z.infer<typeof mediaVideoSchema>;

/**
 * http(s)/data/blob y rutas absolutas web ("/...") se usan tal cual; todo lo
 * demas se resuelve contra `public/` con staticFile().
 */
export const resolveSrc = (src: string): string =>
  /^(https?:|data:|blob:)/i.test(src) || src.startsWith("/") ? src : staticFile(src);

/** Tratamiento fotografico comun: leve contraste, sin filtros "de app". */
export const PHOTO_GRADE = "contrast(1.06) saturate(1.05) brightness(0.98)";

const aspectOf = (p: { width?: number; height?: number }) =>
  p.width && p.height ? p.width / p.height : undefined;

/**
 * Decide si una imagen/video se recorta a pantalla completa ("cover") o se
 * monta en ventana sobre fondo ("window") para no perder la informacion
 * importante (ej. foto apaisada en un reel 9:16).
 */
export const framingFor = (media: { width?: number; height?: number }, frameW: number, frameH: number): "cover" | "window" => {
  const a = aspectOf(media);
  if (!a) return "cover";
  const frameA = frameW / frameH;
  return a / frameA > 1.55 ? "window" : "cover";
};

export const PhotoLayer: React.FC<{
  photo: Photo & { width?: number; height?: number };
  fit?: "cover" | "contain";
  style?: React.CSSProperties;
  grade?: boolean;
}> = ({ photo, fit = "cover", style, grade = true }) => {
  const focus = photo.focus ?? { x: 0.5, y: 0.42 };
  return (
    <Img
      src={resolveSrc(photo.src)}
      style={{
        position: "absolute",
        inset: 0,
        width: "100%",
        height: "100%",
        objectFit: fit,
        objectPosition: `${focus.x * 100}% ${focus.y * 100}%`,
        filter: grade ? PHOTO_GRADE : undefined,
        ...style,
      }}
    />
  );
};

/** Funde arriba y abajo la ventana con el fondo: sin cortes rectangulares duros. */
export const WINDOW_FADE: React.CSSProperties = {
  maskImage: "linear-gradient(to bottom, transparent 0%, #000 14%, #000 80%, transparent 100%)",
  WebkitMaskImage: "linear-gradient(to bottom, transparent 0%, #000 14%, #000 80%, transparent 100%)",
};

/**
 * Foto en "ventana": la imagen completa a todo el ancho y, detras, la misma
 * imagen desenfocada y oscurecida. Da profundidad sin recortar el sujeto.
 */
export const WindowedPhoto: React.FC<{ photo: Photo; top: number; height: number; shade?: string }> = ({
  photo,
  top,
  height,
  shade = "rgba(12,8,18,0.55)",
}) => (
  <AbsoluteFill>
    <PhotoLayer photo={photo} style={{ filter: `blur(46px) ${PHOTO_GRADE}`, scale: "1.25" }} />
    <AbsoluteFill style={{ background: shade }} />
    <div style={{ position: "absolute", left: 0, right: 0, top, height, overflow: "hidden", ...WINDOW_FADE }}>
      <PhotoLayer photo={photo} />
    </div>
  </AbsoluteFill>
);

export const VideoLayer: React.FC<{
  clip: VideoClip;
  fit?: "cover" | "contain";
  style?: React.CSSProperties;
  volume?: number;
}> = ({ clip, fit = "cover", style, volume = 1 }) => {
  const { fps } = useVideoConfig();
  return (
    <Video
      src={resolveSrc(clip.src)}
      trimBefore={Math.round((clip.trimStartSeconds ?? 0) * fps)}
      objectFit={fit}
      muted={!clip.keepAudio}
      volume={clip.keepAudio ? volume : 0}
      style={{ position: "absolute", inset: 0, width: "100%", height: "100%", ...style }}
    />
  );
};
