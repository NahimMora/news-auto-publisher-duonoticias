import type { Content, HookId, TemplateId } from "../../schema/piece";
import { dataHook } from "./DataHook";
import { photoHook } from "./PhotoHook";
import { typographicHook } from "./TypographicHook";
import type { HookDefinition } from "./types";

/** Registro de ganchos. Agregar uno nuevo = importarlo y sumarlo a la lista. */
export const hooks: HookDefinition[] = [typographicHook, photoHook, dataHook];

export const getHook = (id: Exclude<HookId, "auto">): HookDefinition => hooks.find((h) => h.id === id) ?? typographicHook;

/**
 * Resuelve el gancho: respeta la eleccion del editor si es aplicable al
 * contenido (ej. "data" sin cifras cae al mejor alternativo).
 */
export const resolveHook = (requested: HookId, content: Content, template: TemplateId): HookDefinition => {
  if (requested !== "auto") {
    const h = getHook(requested);
    if (h.suits(content, template) > 0) return h;
  }
  return [...hooks].sort((a, b) => b.suits(content, template) - a.suits(content, template))[0];
};
