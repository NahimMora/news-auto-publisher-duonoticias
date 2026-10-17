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
};

export const isStillTemplate = (id: TemplateId) => templateMeta[id]?.still ?? false;
