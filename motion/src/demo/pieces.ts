import type { PieceInput } from "../schema/piece";

/**
 * Piezas de DEMOSTRACION. Las noticias son ficticias (isDemo = true muestra la
 * marca "DEMO · NOTICIA FICTICIA" en cada pieza). Las fotos y el video son de
 * Wikimedia Commons con licencias CC (ver public/demo/CREDITS.md) y no
 * documentan los hechos narrados.
 */

const now = "2026-10-17T14:32:00-03:00";

export const demoBreaking: PieceInput = {
  content: {
    id: "demo-breaking",
    originalTitle: "Ráfagas de viento obligan a suspender el teleférico del cerro San Bernardo",
    headline: "Suspenden el *teleférico* del San Bernardo por ráfagas de viento",
    deck: "Defensa Civil recomendó evitar zonas arboladas y circular con precaución hasta la noche.",
    category: "sociedad",
    location: "Salta Capital",
    date: now,
    source: { name: "Redacción Dúo (demo)" },
    photos: [
      { src: "demo/teleferico.jpg", width: 2000, height: 1500, focus: { x: 0.55, y: 0.45 } },
      { src: "demo/ciudad.jpg", width: 2000, height: 1500, focus: { x: 0.5, y: 0.5 } },
    ],
    highlights: [
      "Las ráfagas superaron los 70 km/h durante la tarde.",
      "El servicio se reanudará cuando mejoren las condiciones.",
    ],
    breaking: true,
    editorialStatus: "review",
    isDemo: true,
  },
  presentation: { template: "breaking", hook: "typographic", format: "reel", durationSeconds: 15 },
};

export const demoEditorial: PieceInput = {
  content: {
    id: "demo-editorial",
    originalTitle: "Cafayate se prepara para una nueva temporada de vendimia",
    headline: "Cafayate se prepara para una vendimia *distinta*",
    deck: "Productores de los Valles Calchaquíes apuestan a combinar enoturismo y cosecha a mano.",
    category: "turismo",
    location: "Cafayate, Salta",
    date: now,
    source: { name: "Redacción Dúo (demo)" },
    videos: [{ src: "demo/cafayate-aereo.mp4", width: 1920, height: 1080, durationSeconds: 16, keepAudio: false }],
    highlights: ["Las bodegas abren sus fincas a visitantes durante la cosecha."],
    quote: { text: "La uva se sigue cortando a mano, como hace cien años.", author: "Productora local (demo)" },
    editorialStatus: "review",
    isDemo: true,
  },
  presentation: { template: "editorial", hook: "photo", format: "reel", durationSeconds: 15 },
};

/** Misma nota que demoEditorial con un video vertical (9:16): va a pantalla completa. */
export const demoEditorialVertical: PieceInput = {
  content: {
    ...demoEditorial.content,
    id: "demo-editorial-vertical",
    videos: [{ src: "demo/cafayate-vertical.mp4", width: 1080, height: 1920, durationSeconds: 16, keepAudio: false }],
  },
  presentation: demoEditorial.presentation,
};

export const demoData: PieceInput = {
  content: {
    id: "demo-data",
    originalTitle: "Balance turístico del fin de semana largo en Salta",
    headline: "Fin de semana largo: así se movió el *turismo* en Salta",
    deck: "Cifras de demostración para mostrar la plantilla de datos.",
    category: "turismo",
    location: "Provincia de Salta",
    date: now,
    source: { name: "Datos ficticios (demo)" },
    photos: [{ src: "demo/cabildo.jpg", width: 2000, height: 877, focus: { x: 0.5, y: 0.5 } }],
    stats: [
      { label: "visitantes recorrieron la provincia", value: 142000, decimals: 0 },
      { label: "de ocupación hotelera en la capital", value: 87, unit: "%", decimals: 0, compareValue: 74, compareLabel: "Año anterior" },
      { label: "gasto promedio diario por turista", value: 68500, prefix: "$", decimals: 0 },
    ],
    editorialStatus: "review",
    isDemo: true,
  },
  presentation: { template: "data", hook: "data", format: "reel", durationSeconds: 16 },
};

export const demoStaticPortrait: PieceInput = {
  content: {
    id: "demo-static-portrait",
    originalTitle: "El Cabildo de Salta renueva su iluminación nocturna",
    headline: "El Cabildo estrena una iluminación que *cambia* la plaza 9 de Julio",
    deck: "",
    category: "cultura",
    location: "Salta Capital",
    date: now,
    source: { name: "Redacción Dúo (demo)" },
    photos: [{ src: "demo/cabildo-vertical.jpg", width: 1500, height: 2000, focus: { x: 0.5, y: 0.4 } }],
    editorialStatus: "review",
    isDemo: true,
  },
  presentation: { template: "static", format: "portrait", staticVariant: "auto", durationSeconds: 5 },
};

export const demoStaticSquare: PieceInput = {
  content: {
    id: "demo-static-square",
    originalTitle: "La Catedral de Salta abre visitas guiadas nocturnas",
    headline: "La Catedral abre sus puertas de noche",
    deck: "",
    category: "turismo",
    location: "Salta Capital",
    date: now,
    source: { name: "Redacción Dúo (demo)" },
    photos: [{ src: "demo/catedral.jpg", width: 1333, height: 2000, focus: { x: 0.5, y: 0.35 } }],
    editorialStatus: "review",
    isDemo: true,
  },
  presentation: { template: "static", format: "square", staticVariant: "auto", durationSeconds: 5 },
};

export const demoStaticType: PieceInput = {
  content: {
    id: "demo-static-type",
    originalTitle: "Paro de transporte anunciado para el lunes",
    headline: "Confirman un paro de colectivos para el lunes en el Valle de Lerma",
    deck: "",
    category: "sociedad",
    location: "Valle de Lerma",
    date: now,
    source: { name: "Redacción Dúo (demo)" },
    photos: [],
    breaking: true,
    editorialStatus: "review",
    isDemo: true,
  },
  presentation: { template: "static", format: "portrait", staticVariant: "auto", durationSeconds: 5 },
};

export const demoStaticSplit: PieceInput = {
  content: {
    id: "demo-static-split",
    originalTitle: "La Municipalidad anunció obras de repavimentación en avenidas del centro de Salta",
    headline: "Repavimentarán seis avenidas del centro y habrá cortes de tránsito *desde el lunes*",
    deck: "",
    category: "sociedad",
    location: "Salta Capital",
    date: now,
    source: { name: "Redacción Dúo (demo)" },
    photos: [{ src: "demo/ciudad.jpg", width: 2000, height: 1500, focus: { x: 0.5, y: 0.5 } }],
    editorialStatus: "review",
    isDemo: true,
  },
  presentation: { template: "static", format: "portrait", staticVariant: "auto", durationSeconds: 5 },
};

export const demoStaticTypeCalm: PieceInput = {
  content: {
    id: "demo-static-type-calm",
    originalTitle: "Abre la inscripción a las becas provinciales para estudiantes universitarios",
    headline: "Abre la inscripción a las becas *universitarias* de la Provincia",
    deck: "",
    category: "educacion",
    location: "Provincia de Salta",
    date: now,
    source: { name: "Redacción Dúo (demo)" },
    photos: [],
    editorialStatus: "review",
    isDemo: true,
  },
  presentation: { template: "static", format: "portrait", staticVariant: "auto", durationSeconds: 5 },
};

export const demoStaticTextSlide: PieceInput = {
  content: { ...demoStaticSplit.content, id: "demo-static-text-slide" },
  presentation: {
    template: "static",
    format: "portrait",
    staticVariant: "auto",
    durationSeconds: 5,
    slide: {
      kind: "text",
      index: 1,
      total: 3,
      text: "Los trabajos empiezan el lunes en avenida Belgrano y siguen por etapas en San Martín, Sarmiento, Entre Ríos, Virrey Toledo y Jujuy. Cada tramo estará cortado entre tres y cinco días y habrá desvíos señalizados para colectivos.",
    },
  },
};

export const demos = {
  breaking: demoBreaking,
  editorial: demoEditorial,
  editorialVertical: demoEditorialVertical,
  data: demoData,
  staticPortrait: demoStaticPortrait,
  staticSquare: demoStaticSquare,
  staticType: demoStaticType,
  staticSplit: demoStaticSplit,
  staticTypeCalm: demoStaticTypeCalm,
  staticTextSlide: demoStaticTextSlide,
};
