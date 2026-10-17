/**
 * Branding del medio. Es el UNICO archivo que hay que tocar para cambiar
 * identidad: nombre, colores, logos, handle y textos fijos.
 *
 * Logos: PNG con transparencia en `public/brand/`. Los actuales se extrajeron
 * de `media/PlantillaPublicaciones.png` (logo real de Duo, blanco). Para mejor
 * nitidez reemplazalos por exportaciones oficiales en alta (ver docs/BRANDING.md),
 * manteniendo los mismos nombres de archivo.
 */
export const brand = {
  name: "Dúo Noticias",
  shortName: "DÚO",
  handle: "@duonoticiasok",
  website: "duonoticiasok.com",
  region: "Salta",
  logos: {
    /** Isotipo + logotipo, blanco, horizontal. */
    horizontal: "brand/logo-horizontal.png",
    horizontalAspect: 672 / 144,
    /** Solo el isotipo (loro), blanco. */
    mark: "brand/logo-mark.png",
    markAspect: 139 / 144,
  },
  colors: {
    /** Violeta institucional (fondo de la plantilla original). */
    primary: "#361957",
    primaryDeep: "#1E0D33",
    /** Ambar institucional (diagonales de la plantilla original). */
    accent: "#FFB700",
    accentSoft: "#FFD36B",
    ink: "#0C0812",
    inkSoft: "#1A1424",
    paper: "#F5F0E6",
    paperShade: "#E7DFCF",
    white: "#FFFFFF",
    /** Senal de urgencia: solo para el punto "en vivo" y la etiqueta de ultimo momento. */
    signal: "#FF3D2E",
  },
  /** Pendiente de la diagonal de la marca (grados respecto de la horizontal). */
  slashAngle: 54,
  copy: {
    breakingLabel: "ÚLTIMO MOMENTO",
    developingLabel: "EN DESARROLLO",
    closingCta: "Seguí la cobertura",
    sourcePrefix: "Fuente",
    swipeHint: "Deslizá",
  },
} as const;

export type Brand = typeof brand;
