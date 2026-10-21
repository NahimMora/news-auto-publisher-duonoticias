import type { FormatId, TemplateId } from "../schema/piece";

/**
 * Metadatos de plantillas sin componentes React: los usan el servidor del
 * panel y el pipeline sin cargar el motor visual.
 */
export type TemplateMeta = {
  id: TemplateId;
  label: string;
  description: string;
  still: boolean;
  formats: FormatId[];
  defaultSeconds: number;
};

export const templateMeta: Record<TemplateId, TemplateMeta> = {
  breaking: {
    id: "breaking",
    label: "Breaking News",
    description: "Último momento: impacto tipográfico, cortes secos y titular condensado.",
    still: false,
    formats: ["reel", "portrait", "square"],
    defaultSeconds: 15,
  },
  editorial: {
    id: "editorial",
    label: "Editorial News",
    description: "Noticia general: serif editorial, panel de papel, cámara lenta y barridas diagonales.",
    still: false,
    formats: ["reel", "portrait", "square"],
    defaultSeconds: 15,
  },
  data: {
    id: "data",
    label: "Data Explainer",
    description: "Cifras protagonistas: contadores, comparaciones y medidores con datos de la nota.",
    still: false,
    formats: ["reel", "portrait", "square"],
    defaultSeconds: 16,
  },
  static: {
    id: "static",
    label: "Static Editorial Post",
    description: "Post estático: variantes hero, split y tipográfica según foto y largo del titular.",
    still: true,
    formats: ["portrait", "square", "reel"],
    defaultSeconds: 5,
  },
  video: {
    id: "video",
    label: "Video News",
    description: "Reel de video real: titular fijo, video completo sin fondo desenfocado y \"Qué se sabe\" rotando.",
    still: false,
    formats: ["reel"],
    defaultSeconds: 30,
  },
  cover: {
    id: "cover",
    label: "Portada de video",
    description: "Portada 9:16 del reel con todo lo importante dentro del recorte 4:5 del feed.",
    still: true,
    formats: ["reel"],
    defaultSeconds: 5,
  },
  board: {
    id: "board",
    label: "Tablero de servicio",
    description: "Resumen de las 8, clima SMN, dólar, feriados y servicios (agua, luz, pasos) con datos oficiales.",
    still: true,
    formats: ["portrait", "reel"],
    defaultSeconds: 5,
  },
  story: {
    id: "story",
    label: "Historia",
    description: "Historia 9:16: post nuevo, último momento, lo más importante del día y actualizaciones.",
    still: true,
    formats: ["reel"],
    defaultSeconds: 5,
  },
  weekly: {
    id: "weekly",
    label: "Top 5 de la semana",
    description: "Reel de los domingos: cuenta regresiva de las 5 notas más vistas de la semana.",
    still: false,
    formats: ["reel"],
    defaultSeconds: 24,
  },
};

export const isStillTemplate = (id: TemplateId) => templateMeta[id]?.still ?? false;
