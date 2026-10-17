import { brand } from "../../brand/brand.config";

const cot = (deg: number) => 1 / Math.tan((deg * Math.PI) / 180);

/**
 * Poligono de recorte para una barrida diagonal con la pendiente de la marca
 * ("/"). `p` = 0 nada visible, 1 todo visible. `from` indica de donde entra.
 * Devuelve un clip-path en px para un rectangulo w x h.
 */
export const slashClip = (
  p: number,
  w: number,
  h: number,
  from: "left" | "right" = "left",
  angle: number = brand.slashAngle,
): string => {
  const run = h * cot(angle);
  const travel = w + run;
  if (from === "left") {
    const o = p * travel; // x en y=0
    const xTop = o;
    const xBottom = o - run;
    return `polygon(-2px -2px, ${xTop}px -2px, ${xBottom}px ${h + 2}px, -2px ${h + 2}px)`;
  }
  const o = w - p * travel;
  const xTop = o + run;
  const xBottom = o;
  return `polygon(${xTop}px -2px, ${w + 2}px -2px, ${w + 2}px ${h + 2}px, ${xBottom}px ${h + 2}px)`;
};

/**
 * Banda diagonal (el "corte" de la marca) centrada en la posicion `p` de una
 * barrida. Se usa como borde de luz ambar durante transiciones.
 */
export const slashBand = (p: number, w: number, h: number, thickness: number, angle: number = brand.slashAngle): string => {
  const run = h * cot(angle);
  const travel = w + run + thickness;
  const o = p * travel;
  const a = o - thickness;
  return `polygon(${a}px 0px, ${o}px 0px, ${o - run}px ${h}px, ${a - run}px ${h}px)`;
};

/** Ranura diagonal que se abre desde el centro (revelado fotografico). */
export const slitClip = (p: number, w: number, h: number, angle: number = brand.slashAngle): string => {
  const run = h * cot(angle);
  const cx = w / 2;
  const half = (p * (w + run)) / 2 + 1;
  const topL = cx + run / 2 - half;
  const topR = cx + run / 2 + half;
  const botL = cx - run / 2 - half;
  const botR = cx - run / 2 + half;
  return `polygon(${topL}px 0px, ${topR}px 0px, ${botR}px ${h}px, ${botL}px ${h}px)`;
};

/** Paralelogramo con la pendiente de la marca, para etiquetas. */
export const parallelogram = (w: number, h: number, angle: number = brand.slashAngle): string => {
  const run = h * cot(angle);
  return `polygon(${run}px 0px, ${w}px 0px, ${w - run}px ${h}px, 0px ${h}px)`;
};

export const slashRun = (h: number, angle: number = brand.slashAngle) => h * cot(angle);

/**
 * Triangulo de esquina con la pendiente de la marca (como las esquinas ambar
 * de la plantilla original). `size` = fraccion del ancho que ocupa el cateto.
 */
export const slashCorner = (
  p: number,
  w: number,
  h: number,
  corner: "top-left" | "bottom-right",
  size: number,
  angle: number = brand.slashAngle,
): string => {
  const leg = w * size * p;
  const run = leg * Math.tan((angle * Math.PI) / 180);
  if (corner === "top-left") return `polygon(0px 0px, ${leg}px 0px, 0px ${run}px)`;
  return `polygon(${w}px ${h}px, ${w - leg}px ${h}px, ${w}px ${h - run}px)`;
};

/** Filos de la ranura diagonal (dos bandas finas a los lados del recorte). */
export const slitEdges = (p: number, w: number, h: number, thickness: number, angle: number = brand.slashAngle): [string, string] => {
  const run = h * cot(angle);
  const cx = w / 2;
  const half = (p * (w + run)) / 2 + 1;
  const topL = cx + run / 2 - half;
  const topR = cx + run / 2 + half;
  const botL = cx - run / 2 - half;
  const botR = cx - run / 2 + half;
  return [
    `polygon(${topL - thickness}px 0px, ${topL}px 0px, ${botL}px ${h}px, ${botL - thickness}px ${h}px)`,
    `polygon(${topR}px 0px, ${topR + thickness}px 0px, ${botR + thickness}px ${h}px, ${botR}px ${h}px)`,
  ];
};
