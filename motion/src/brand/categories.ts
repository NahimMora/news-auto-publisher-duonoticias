import { brand } from "./brand.config";

/**
 * Categorias informativas. `accent` tine etiquetas, subrayados y barras; nunca
 * el titular completo. Agregar una categoria = agregar una entrada.
 */
export const categories = {
  actualidad: { label: "Actualidad", accent: brand.colors.accent },
  policiales: { label: "Policiales", accent: "#FF6A3D" },
  justicia: { label: "Justicia", accent: "#C7A6FF" },
  politica: { label: "Política", accent: "#8F7BFF" },
  economia: { label: "Economía", accent: "#2ED394" },
  sociedad: { label: "Sociedad", accent: "#48B0FF" },
  salud: { label: "Salud", accent: "#3FD9CB" },
  educacion: { label: "Educación", accent: "#7FD1FF" },
  deportes: { label: "Deportes", accent: "#B6F03C" },
  cultura: { label: "Cultura", accent: "#FF8AD0" },
  espectaculos: { label: "Espectáculos", accent: "#FF5FA8" },
  turismo: { label: "Turismo", accent: brand.colors.accentSoft },
  clima: { label: "Clima", accent: "#6CC9FF" },
  tecnologia: { label: "Tecnología", accent: "#5BE0FF" },
} as const;

export type CategoryId = keyof typeof categories;

export const categoryIds = Object.keys(categories) as [CategoryId, ...CategoryId[]];

export const getCategory = (id: string | undefined) => {
  const key = (id ?? "actualidad") as CategoryId;
  return categories[key] ?? categories.actualidad;
};
