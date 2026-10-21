import type { FormatId } from "../schema/piece";

/**
 * Grilla y zonas seguras por formato. Todo lo que se posiciona usa estas
 * metricas: nada se recorta de un formato a otro, se recalcula.
 */
export const formats = {
  reel: { width: 1080, height: 1920, label: "Reel / Story 9:16" },
  portrait: { width: 1080, height: 1350, label: "Post vertical 4:5" },
  square: { width: 1080, height: 1080, label: "Post cuadrado 1:1" },
} as const;

export type Layout = {
  format: FormatId;
  width: number;
  height: number;
  /** Unidad base: 1 en 1080 px de ancho. */
  u: number;
  /** Margen lateral de contenido. */
  margin: number;
  /** Borde superior util (debajo de la UI de Instagram en reels). */
  safeTop: number;
  /** Borde inferior util (encima de caption/botones en reels). */
  safeBottom: number;
  /** Margen derecho extra para la columna de botones en reels. */
  safeRight: number;
  contentWidth: number;
  /** Escala tipografica base para este formato. */
  type: {
    headlineMax: number;
    headlineMin: number;
    headlineLines: number;
    /** Lineas preferidas del titular (ver fitTextBlock.preferLines). */
    headlinePrefer: number;
    deck: number;
    kicker: number;
    meta: number;
    data: number;
  };
  /** Columnas de 12 con gutter. */
  col: (n: number) => number;
  gutter: number;
};

export const getLayout = (format: FormatId, width?: number, height?: number): Layout => {
  const f = formats[format];
  const W = width ?? f.width;
  const H = height ?? f.height;
  const u = W / 1080;
  const margin = Math.round(84 * u);
  const isReel = format === "reel";
  const isSquare = format === "square";
  // Reels: Instagram tapa ~220px arriba (cabecera) y ~420px abajo (caption,
  // audio, CTA); la columna de acciones ocupa ~120px a la derecha.
  const safeTop = Math.round((isReel ? 230 : isSquare ? 70 : 80) * u);
  const safeBottom = Math.round((isReel ? 430 : isSquare ? 70 : 84) * u);
  const safeRight = Math.round((isReel ? 132 : 0) * u);
  const contentWidth = W - margin * 2 - safeRight;
  const gutter = Math.round(24 * u);
  const col = (n: number) => ((contentWidth + gutter) / 12) * n - gutter;
  return {
    format,
    width: W,
    height: H,
    u,
    margin,
    safeTop,
    safeBottom,
    safeRight,
    contentWidth,
    gutter,
    col,
    type: {
      headlineMax: Math.round((isReel ? 132 : isSquare ? 104 : 116) * u),
      headlineMin: Math.round((isReel ? 72 : isSquare ? 58 : 64) * u),
      headlineLines: isReel ? 5 : isSquare ? 4 : 5,
      headlinePrefer: isReel ? 4 : 3,
      deck: Math.round((isReel ? 46 : 40) * u),
      kicker: Math.round((isReel ? 30 : 27) * u),
      meta: Math.round((isReel ? 25 : 22) * u),
      data: Math.round((isReel ? 300 : isSquare ? 220 : 250) * u),
    },
  };
};
