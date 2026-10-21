import type { TextRole } from "./tokens";
import { upper } from "./tokens";

/**
 * Motor de composicion de titulares.
 *
 * Mide con canvas usando exactamente la misma fuente, peso, ancho y tracking
 * que el render, parte el texto en lineas deterministicas (las animaciones por
 * linea dependen de esto) y busca el cuerpo mas grande que entra en N lineas.
 * Nunca recorta texto: si no entra al minimo devuelve `overflow: true` para que
 * el panel o el pipeline propongan un titular audiovisual mas corto.
 */

export type Token = { text: string; emphasis: boolean };
export type LaidLine = { tokens: Token[]; width: number };
export type TextBlockLayout = {
  lines: LaidLine[];
  fontSize: number;
  lineHeightPx: number;
  height: number;
  maxLineWidth: number;
  overflow: boolean;
};

const STRETCH_KEYWORD: Record<number, string> = {
  62.5: "extra-condensed",
  75: "condensed",
  87.5: "semi-condensed",
  100: "normal",
  112.5: "semi-expanded",
  125: "expanded",
};

let ctx: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D | null = null;
const getCtx = () => {
  if (ctx) return ctx;
  if (typeof OffscreenCanvas !== "undefined") {
    ctx = new OffscreenCanvas(8, 8).getContext("2d");
  } else if (typeof document !== "undefined") {
    ctx = document.createElement("canvas").getContext("2d");
  }
  return ctx;
};

const cache = new Map<string, number>();

/** Ancho en px de `text` con el rol dado (sin transformar mayusculas). */
export const measure = (text: string, role: TextRole, fontSize: number, italic = role.italic ?? false): number => {
  const key = `${role.family}|${role.weight}|${role.stretch}|${italic}|${role.letterSpacing}|${fontSize}|${text}`;
  const hit = cache.get(key);
  if (hit !== undefined) return hit;
  const c = getCtx();
  let width: number;
  if (!c) {
    // Sin canvas (SSR del panel): estimacion conservadora.
    width = text.length * fontSize * 0.56 * (role.stretch / 100);
  } else {
    c.font = `${italic ? "italic " : ""}${role.weight} ${fontSize}px ${role.family}`;
    const anyCtx = c as unknown as { fontStretch?: string; letterSpacing?: string };
    anyCtx.fontStretch = STRETCH_KEYWORD[role.stretch] ?? "normal";
    anyCtx.letterSpacing = `${role.letterSpacing * fontSize}px`;
    width = c.measureText(text).width;
  }
  cache.set(key, width);
  return width;
};

/**
 * Tokeniza un titular. `*palabra*` o `*dos palabras*` marca enfasis.
 * Los saltos de linea los decide el motor, no el texto.
 */
export const tokenize = (raw: string, uppercase = false): Token[] => {
  const tokens: Token[] = [];
  const parts = raw.replace(/\s+/g, " ").trim().split(/(\*[^*]+\*)/g);
  for (const part of parts) {
    if (!part) continue;
    const emphasis = part.startsWith("*") && part.endsWith("*") && part.length > 2;
    const body = emphasis ? part.slice(1, -1) : part;
    for (const word of body.split(" ")) {
      if (!word) continue;
      tokens.push({ text: uppercase ? upper(word) : word, emphasis });
    }
  }
  return tokens;
};

export const stripEmphasis = (raw: string) => raw.replace(/\*/g, "");

type WrapOpts = {
  role: TextRole;
  fontSize: number;
  maxWidth: number;
  /** Las palabras enfatizadas usan italica (titular editorial). */
  emphasisItalic?: boolean;
};

const tokenWidth = (t: Token, o: WrapOpts) =>
  measure(t.text, o.role, o.fontSize, o.emphasisItalic && t.emphasis ? true : (o.role.italic ?? false));

const wrapGreedy = (tokens: Token[], o: WrapOpts, width: number): LaidLine[] => {
  const space = measure(" ", o.role, o.fontSize);
  const lines: LaidLine[] = [];
  let current: Token[] = [];
  let currentWidth = 0;
  for (const t of tokens) {
    const w = tokenWidth(t, o);
    const next = current.length === 0 ? w : currentWidth + space + w;
    if (current.length > 0 && next > width) {
      lines.push({ tokens: current, width: currentWidth });
      current = [t];
      currentWidth = w;
    } else {
      current.push(t);
      currentWidth = next;
    }
  }
  if (current.length) lines.push({ tokens: current, width: currentWidth });
  return lines;
};

/**
 * Lineas equilibradas: busca el ancho minimo que mantiene la misma cantidad de
 * lineas (equivalente a `text-wrap: balance`) para evitar viudas.
 */
export const wrapBalanced = (tokens: Token[], o: WrapOpts): LaidLine[] => {
  const base = wrapGreedy(tokens, o, o.maxWidth);
  if (base.length <= 1) return base;
  let lo = o.maxWidth * 0.5;
  let hi = o.maxWidth;
  let best = base;
  for (let i = 0; i < 14; i++) {
    const mid = (lo + hi) / 2;
    const attempt = wrapGreedy(tokens, o, mid);
    if (attempt.length <= base.length && attempt.every((l) => l.width <= o.maxWidth)) {
      best = attempt;
      hi = mid;
    } else {
      lo = mid;
    }
  }
  return best;
};

export type FitOpts = {
  text: string;
  role: TextRole;
  maxWidth: number;
  maxLines: number;
  minSize: number;
  maxSize: number;
  /** Alto maximo opcional del bloque. */
  maxHeight?: number;
  emphasisItalic?: boolean;
  balance?: boolean;
  /**
   * Cantidad de lineas preferida. Entre los cuerpos que entran, se elige el
   * que maximiza tamano penalizando cada linea extra (titulares mas anchos y
   * compactos en vez de columnas angostas de 5-6 lineas).
   */
  preferLines?: number;
};

/** Cuerpo mas grande (paso 2px) que entra en `maxLines` y `maxHeight`. */
export const fitTextBlock = (o: FitOpts): TextBlockLayout => {
  const tokens = tokenize(o.text, o.role.uppercase ?? false);
  const safety = 0.985; // margen para hinting/ejes opticos
  const width = o.maxWidth * safety;
  const build = (fontSize: number): TextBlockLayout => {
    const wo: WrapOpts = { role: o.role, fontSize, maxWidth: width, emphasisItalic: o.emphasisItalic };
    const lines = o.balance === false ? wrapGreedy(tokens, wo, width) : wrapBalanced(tokens, wo);
    const lineHeightPx = fontSize * o.role.lineHeight;
    const maxLineWidth = Math.max(0, ...lines.map((l) => l.width));
    const height = lines.length * lineHeightPx;
    const tooWide = lines.some((l) => l.width > width + 0.5);
    const overflow =
      tooWide || lines.length > o.maxLines || (o.maxHeight !== undefined && height > o.maxHeight);
    return { lines, fontSize, lineHeightPx, height, maxLineWidth, overflow };
  };
  let best: TextBlockLayout | null = null;
  let bestScore = -1;
  for (let size = o.maxSize; size >= o.minSize; size -= 2) {
    const layout = build(size);
    if (layout.overflow) continue;
    if (o.preferLines === undefined) return layout;
    const extra = Math.max(0, layout.lines.length - o.preferLines);
    const score = size * Math.pow(0.86, extra);
    if (score > bestScore) {
      best = layout;
      bestScore = score;
    }
    if (extra === 0) break; // cuerpos menores con las mismas lineas solo achican
  }
  return best ?? build(o.minSize);
};

/** Parrafo de texto corrido (bajadas, puntos clave): ancho fijo, cuerpo fijo. */
export const layoutParagraph = (text: string, role: TextRole, fontSize: number, maxWidth: number): TextBlockLayout => {
  const tokens = tokenize(text, role.uppercase ?? false);
  const lines = wrapBalanced(tokens, { role, fontSize, maxWidth: maxWidth * 0.985 });
  const lineHeightPx = fontSize * role.lineHeight;
  return {
    lines,
    fontSize,
    lineHeightPx,
    height: lines.length * lineHeightPx,
    maxLineWidth: Math.max(0, ...lines.map((l) => l.width)),
    overflow: false,
  };
};

/**
 * Sugerencia de titular audiovisual mas corto SIN reescribir el sentido:
 * solo recorta a la primera clausula (antes de ":", " - ", ",") si existe.
 * La decision final queda en manos del editor (panel) o del editorial IA.
 */
export const suggestShorterHeadline = (headline: string, maxChars: number): string | null => {
  const clean = stripEmphasis(headline).trim();
  if (clean.length <= maxChars) return null;
  for (const sep of [": ", " - ", " — ", ", "]) {
    const idx = clean.indexOf(sep);
    if (idx > 12 && idx <= maxChars) return clean.slice(0, idx).trim();
  }
  return null;
};

/** Cuerpo para que una sola linea (cifras) ocupe `maxWidth`, acotado a `maxSize`. */
export const fitSingleLine = (text: string, role: TextRole, maxWidth: number, maxSize: number, minSize = 40): number => {
  const at100 = measure(text, role, 100);
  if (at100 <= 0) return maxSize;
  return Math.max(minSize, Math.min(maxSize, Math.floor((maxWidth / at100) * 100 * 0.98)));
};
