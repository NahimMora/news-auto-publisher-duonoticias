import { z } from "zod";
import { categoryIds } from "../brand/categories";

/**
 * Modelo de datos. Una pieza = CONTENIDO (lo que informa la noticia, nunca lo
 * cambia el editor visual) + PRESENTACION (decisiones visuales editables).
 */

// ---------- Contenido ----------

export const mediaPhotoSchema = z.object({
  /** URL http(s), ruta relativa a `public/` o ruta absoluta (el renderer la copia). */
  src: z.string().min(1),
  credit: z.string().optional(),
  /** Punto de interes 0..1 para recortes y movimientos de camara. */
  focus: z.object({ x: z.number().min(0).max(1), y: z.number().min(0).max(1) }).optional(),
  /** Dimensiones originales (px): deciden recorte "cover" o montaje en ventana. */
  width: z.number().positive().optional(),
  height: z.number().positive().optional(),
});

export const mediaVideoSchema = z.object({
  src: z.string().min(1),
  durationSeconds: z.number().positive().optional(),
  /** Segundos a saltear al inicio del clip. */
  trimStartSeconds: z.number().min(0).default(0),
  credit: z.string().optional(),
  width: z.number().positive().optional(),
  height: z.number().positive().optional(),
  /** Conservar el audio original (reels de video). */
  keepAudio: z.boolean().default(true),
});

export const statSchema = z.object({
  label: z.string().min(1),
  value: z.number(),
  unit: z.string().optional(),
  prefix: z.string().optional(),
  decimals: z.number().int().min(0).max(3).default(0),
  /** Valor de comparacion opcional (ej. anio anterior). Debe venir de la nota. */
  compareValue: z.number().optional(),
  compareLabel: z.string().optional(),
});

export const editorialStatusSchema = z.enum(["draft", "review", "approved", "published", "rejected"]);

export const contentSchema = z.object({
  id: z.string().min(1),
  originalTitle: z.string().min(1),
  /** Titular audiovisual. Admite *enfasis* con asteriscos en UNA o dos palabras. */
  headline: z.string().min(1),
  deck: z.string().default(""),
  category: z.enum(categoryIds).default("actualidad"),
  location: z.string().optional(),
  /** ISO 8601. */
  date: z.string(),
  source: z.object({ name: z.string().min(1), url: z.string().optional() }),
  photos: z.array(mediaPhotoSchema).default([]),
  videos: z.array(mediaVideoSchema).default([]),
  /** Puntos clave (1 a 3) tomados de la nota. */
  highlights: z.array(z.string()).max(4).default([]),
  stats: z.array(statSchema).max(4).default([]),
  quote: z.object({ text: z.string(), author: z.string() }).optional(),
  breaking: z.boolean().default(false),
  editorialStatus: editorialStatusSchema.default("draft"),
  /** Marca visible en piezas de demostracion. */
  isDemo: z.boolean().default(false),
});

// ---------- Presentacion ----------

export const templateIds = ["breaking", "editorial", "data", "static"] as const;
export const hookIds = ["auto", "typographic", "photo", "data"] as const;
export const formatIds = ["reel", "portrait", "square"] as const;
export const staticVariantIds = ["auto", "hero", "split", "type"] as const;
export const easingIds = ["snap", "glide", "punch", "linear"] as const;

export const animationSchema = z.object({
  /** 0 = sobrio, 1 = estandar, 1.6 = enfatico. Escala desplazamientos y escalas. */
  intensity: z.number().min(0).max(1.6).default(1),
  /** Multiplicador de velocidad global de entradas. */
  speed: z.number().min(0.6).max(1.6).default(1),
  easing: z.enum(easingIds).default("snap"),
  stiffness: z.number().min(20).max(400).default(170),
  damping: z.number().min(6).max(200).default(22),
  /** Zoom total de camara virtual sobre la foto o video (1 = sin zoom). */
  cameraZoom: z.number().min(1).max(1.4).default(1.12),
});

export const presentationSchema = z.object({
  template: z.enum(templateIds).default("editorial"),
  hook: z.enum(hookIds).default("auto"),
  format: z.enum(formatIds).default("reel"),
  durationSeconds: z.number().min(5).max(180).default(15),
  staticVariant: z.enum(staticVariantIds).default("auto"),
  /** Color de acento; vacio = el de la categoria. */
  accent: z.string().optional(),
  /** light = panel papel (editorial). Breaking y data son siempre oscuros. */
  theme: z.enum(["dark", "light"]).default("light"),
  animation: animationSchema.default({
    intensity: 1,
    speed: 1,
    easing: "snap",
    stiffness: 170,
    damping: 22,
    cameraZoom: 1.12,
  }),
  audio: z.object({ src: z.string(), volume: z.number().min(0).max(1).default(0.6) }).optional(),
  /** Slide de carrusel (solo template static): portada, foto o texto. */
  slide: z
    .object({
      kind: z.enum(["cover", "photo", "text"]),
      index: z.number().int().min(0),
      total: z.number().int().min(1),
      text: z.string().optional(),
    })
    .optional(),
});

export const pieceSchema = z.object({
  content: contentSchema,
  presentation: presentationSchema,
});

export type Content = z.infer<typeof contentSchema>;
export type Presentation = z.infer<typeof presentationSchema>;
export type AnimationConfig = z.infer<typeof animationSchema>;
export type Piece = z.infer<typeof pieceSchema>;
export type PieceInput = z.input<typeof pieceSchema>;
export type TemplateId = (typeof templateIds)[number];
export type HookId = (typeof hookIds)[number];
export type FormatId = (typeof formatIds)[number];
export type Stat = z.infer<typeof statSchema>;

/** Proyecto de edicion guardado (panel). */
export const projectSchema = z.object({
  id: z.string(),
  name: z.string(),
  piece: pieceSchema,
  createdAt: z.string(),
  updatedAt: z.string(),
  origin: z.enum(["manual", "pipeline", "wordpress"]).default("manual"),
});
export type Project = z.infer<typeof projectSchema>;
