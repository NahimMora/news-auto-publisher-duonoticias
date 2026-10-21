import type React from "react";
import type { Layout } from "../../design/layout";
import type { Content, HookId, TemplateId } from "../../schema/piece";

export type HookProps = {
  content: Content;
  layout: Layout;
  accent: string;
  template: TemplateId;
  /** Frames del gancho (la salida ocurre al final de este tramo). */
  durationFrames: number;
};

/**
 * Un gancho controla los primeros 1-2 segundos. Se monta encima del escenario
 * y su salida revela la escena. Para agregar uno nuevo: crear el componente,
 * describir para que contenido sirve (`suits`) y registrarlo en registry.ts.
 */
export type HookDefinition = {
  id: Exclude<HookId, "auto">;
  label: string;
  description: string;
  seconds: number;
  Overlay: React.FC<HookProps>;
  /** Si es true el template envuelve el escenario con el revelado del gancho. */
  revealsStage?: boolean;
  /** Puntaje de afinidad 0..1 para la eleccion automatica. */
  suits: (content: Content, template: TemplateId) => number;
};
