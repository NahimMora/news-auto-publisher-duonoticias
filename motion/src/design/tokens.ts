import type { CSSProperties } from "react";
import { fontFamilies } from "./fonts";

/**
 * Roles tipograficos. Cada rol define familia y ejes; el tamano lo decide el
 * layout (escala por formato) o el ajuste automatico de titulares.
 *
 * `stretch` solo admite los porcentajes de las palabras clave CSS
 * (62.5, 75, 87.5, 100, 112.5, 125) para que la medicion en canvas coincida
 * exactamente con el render.
 */
export type TextRole = {
  family: string;
  weight: number;
  stretch: 62.5 | 75 | 87.5 | 100 | 112.5 | 125;
  italic?: boolean;
  uppercase?: boolean;
  /** em */
  letterSpacing: number;
  lineHeight: number;
  variation?: string;
};

export const textRoles = {
  /** Titular de urgencia: condensada, negra, mayusculas. */
  breakingHeadline: {
    family: fontFamilies.display,
    weight: 880,
    stretch: 75,
    uppercase: true,
    letterSpacing: -0.008,
    // 0.95: las tildes de mayusculas (Á, É) no chocan con la linea superior.
    lineHeight: 0.95,
  },
  /** Titular editorial: serif optica, caja baja. */
  editorialHeadline: {
    family: fontFamilies.serif,
    weight: 560,
    stretch: 100,
    letterSpacing: -0.018,
    lineHeight: 1.0,
    variation: '"SOFT" 30, "WONK" 0',
  },
  /** Titular de post estatico: display semicondensada. */
  postHeadline: {
    family: fontFamilies.display,
    weight: 820,
    stretch: 87.5,
    letterSpacing: -0.014,
    lineHeight: 0.98,
  },
  /** Cifras protagonistas. */
  dataNumber: {
    family: fontFamilies.display,
    weight: 900,
    stretch: 75,
    letterSpacing: -0.02,
    lineHeight: 0.85,
  },
  /** Bajada y puntos clave. */
  deck: {
    family: fontFamilies.display,
    weight: 470,
    stretch: 100,
    letterSpacing: -0.004,
    lineHeight: 1.22,
  },
  deckStrong: {
    family: fontFamilies.display,
    weight: 640,
    stretch: 100,
    letterSpacing: -0.006,
    lineHeight: 1.18,
  },
  /** Etiquetas de categoria. */
  kicker: {
    family: fontFamilies.display,
    weight: 780,
    stretch: 112.5,
    uppercase: true,
    letterSpacing: 0.06,
    lineHeight: 1,
  },
  /** Fecha, fuente, ubicacion, creditos. */
  meta: {
    family: fontFamilies.mono,
    weight: 560,
    stretch: 100,
    uppercase: true,
    letterSpacing: 0.08,
    lineHeight: 1.1,
  },
  quote: {
    family: fontFamilies.serif,
    weight: 420,
    stretch: 100,
    italic: true,
    letterSpacing: -0.01,
    lineHeight: 1.12,
    variation: '"SOFT" 60, "WONK" 1',
  },
} satisfies Record<string, TextRole>;

export type TextRoleId = keyof typeof textRoles;

export const roleStyle = (role: TextRole, fontSize: number): CSSProperties => ({
  fontFamily: role.family,
  fontWeight: role.weight,
  fontStretch: `${role.stretch}%`,
  fontStyle: role.italic ? "italic" : "normal",
  letterSpacing: `${role.letterSpacing}em`,
  lineHeight: role.lineHeight,
  fontSize,
  fontVariationSettings: role.variation,
  fontOpticalSizing: "auto",
  fontKerning: "normal",
  textTransform: "none",
  whiteSpace: "pre",
});

export const upper = (text: string) => text.toLocaleUpperCase("es-AR");
