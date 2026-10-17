import { loadFont } from "@remotion/fonts";
import { staticFile } from "remotion";

/**
 * Tipografias locales (SIL OFL, licencias en public/fonts/OFL-*.txt):
 * - Display/Texto: Archivo variable (peso 100-900, ancho 62-125%). Condensada
 *   para urgencia, normal para texto, expandida para etiquetas.
 * - Editorial: Fraunces variable (serif con eje optico y SOFT).
 * - Meta/datos: JetBrains Mono variable.
 */
export const fontFamilies = {
  display: "DuoArchivo",
  serif: "DuoFraunces",
  mono: "DuoMono",
} as const;

export const fontStack = {
  display: `${fontFamilies.display}, "Arial Narrow", Arial, sans-serif`,
  serif: `${fontFamilies.serif}, Georgia, serif`,
  mono: `${fontFamilies.mono}, Consolas, monospace`,
} as const;

let fontsPromise: Promise<void> | null = null;

export const loadBrandFonts = (): Promise<void> => {
  if (!fontsPromise) {
    fontsPromise = Promise.all([
      loadFont({
        family: fontFamilies.display,
        url: staticFile("fonts/Archivo-Variable.woff2"),
        weight: "100 900",
        stretch: "62% 125%",
        style: "normal",
        display: "block",
      }),
      loadFont({
        family: fontFamilies.display,
        url: staticFile("fonts/Archivo-Variable-Italic.woff2"),
        weight: "100 900",
        stretch: "62% 125%",
        style: "italic",
        display: "block",
      }),
      loadFont({
        family: fontFamilies.serif,
        url: staticFile("fonts/Fraunces-Variable.woff2"),
        weight: "100 900",
        style: "normal",
        display: "block",
      }),
      loadFont({
        family: fontFamilies.serif,
        url: staticFile("fonts/Fraunces-Variable-Italic.woff2"),
        weight: "100 900",
        style: "italic",
        display: "block",
      }),
      loadFont({
        family: fontFamilies.mono,
        url: staticFile("fonts/JetBrainsMono-Variable.woff2"),
        weight: "100 800",
        style: "normal",
        display: "block",
      }),
    ]).then(() => undefined);
  }
  return fontsPromise;
};
