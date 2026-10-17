import type React from "react";
import type { TemplateId } from "../schema/piece";
import { BreakingNews } from "./BreakingNews";
import { DataExplainer } from "./DataExplainer";
import { EditorialNews } from "./EditorialNews";
import { templateMeta, type TemplateMeta } from "./meta";
import type { TemplateProps } from "./shared";
import { StaticPost } from "./StaticPost";

/**
 * Registro de plantillas. Agregar una plantilla nueva no toca a las demas:
 * crear el componente en templates/, sumar su metadata en meta.ts y su
 * componente aca.
 */
export type TemplateDefinition = TemplateMeta & { component: React.FC<TemplateProps> };

const components: Record<TemplateId, React.FC<TemplateProps>> = {
  breaking: BreakingNews,
  editorial: EditorialNews,
  data: DataExplainer,
  static: StaticPost,
};

export const getTemplate = (id: TemplateId): TemplateDefinition => {
  const meta = templateMeta[id] ?? templateMeta.breaking;
  return { ...meta, component: components[meta.id] };
};

export const listTemplates = (): TemplateDefinition[] => (Object.keys(templateMeta) as TemplateId[]).map(getTemplate);
