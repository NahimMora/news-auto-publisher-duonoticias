"use client";

import type { Piece, PieceInput, Project } from "../../src/schema/piece";

/** Cliente HTTP del panel (rutas /api del mismo servidor local). */

const json = async <T,>(res: Response): Promise<T> => {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { error?: string }).error ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
};

export const api = {
  listProjects: () => fetch("/api/projects", { cache: "no-store" }).then((r) => json<Project[]>(r)),
  getProject: (id: string) => fetch(`/api/projects/${id}`, { cache: "no-store" }).then((r) => json<Project>(r)),
  createProject: (body: { name?: string; piece?: PieceInput; demo?: string; origin?: Project["origin"] }) =>
    fetch("/api/projects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then((r) => json<Project>(r)),
  saveProject: (id: string, body: { name?: string; piece?: Piece }) =>
    fetch(`/api/projects/${id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then((r) => json<Project>(r)),
  deleteProject: (id: string) => fetch(`/api/projects/${id}`, { method: "DELETE" }),
  upload: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetch("/api/upload", { method: "POST", body: form }).then((r) => json<{ src: string; name: string; size: number }>(r));
  },
  startRender: (projectId: string, kind: "auto" | "mp4" | "png" | "jpeg") =>
    fetch("/api/render", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ projectId, kind }) }).then((r) =>
      json<RenderJobDTO>(r),
    ),
  renderStatus: (jobId: string) => fetch(`/api/render/${jobId}`, { cache: "no-store" }).then((r) => json<RenderJobDTO>(r)),
  inbox: () => fetch("/api/inbox", { cache: "no-store" }).then((r) => json<Array<{ file: string; piece: PieceInput; receivedAt: string }>>(r)),
  wordpress: () => fetch("/api/wordpress", { cache: "no-store" }).then((r) => json<{ demo: boolean; pieces: PieceInput[] }>(r)),
};

export type RenderJobDTO = {
  id: string;
  status: "queued" | "bundling" | "rendering" | "done" | "error";
  progress: number;
  file?: string;
  error?: string;
  ms?: number;
};

/**
 * Traduce las rutas de la pieza a URLs que el navegador puede cargar:
 * - uploads/... -> /api/media/uploads/...
 * - rutas absolutas del pipeline -> /api/media/abs?p=...
 * - demo/, brand/ (public) quedan igual (staticFile las resuelve).
 */
export const toBrowserSrc = (src: string): string => {
  if (/^(https?:|data:|blob:)/i.test(src) || src.startsWith("/api/")) return src;
  if (src.startsWith("uploads/")) return `/api/media/${src}`;
  if (/^[a-zA-Z]:[\\/]/.test(src) || src.startsWith("\\\\") || src.startsWith("file:")) return `/api/media/abs?p=${encodeURIComponent(src.replace(/^file:\/+/, ""))}`;
  // Archivos de public/ (demo/, brand/): ruta absoluta del sitio.
  return src.startsWith("/") ? src : `/${src}`;
};

export const toPlayerPiece = (piece: Piece): Piece => ({
  ...piece,
  content: {
    ...piece.content,
    photos: piece.content.photos.map((p) => ({ ...p, src: toBrowserSrc(p.src) })),
    videos: piece.content.videos.map((v) => ({ ...v, src: toBrowserSrc(v.src) })),
  },
  presentation: {
    ...piece.presentation,
    audio: piece.presentation.audio ? { ...piece.presentation.audio, src: toBrowserSrc(piece.presentation.audio.src) } : undefined,
  },
});

/** Mide una imagen o video en el navegador (dimensiones y duracion). */
export const probeMedia = (url: string, kind: "image" | "video"): Promise<{ width: number; height: number; duration?: number }> =>
  new Promise((resolve, reject) => {
    if (kind === "image") {
      const img = new Image();
      img.onload = () => resolve({ width: img.naturalWidth, height: img.naturalHeight });
      img.onerror = () => reject(new Error("No se pudo leer la imagen"));
      img.src = url;
    } else {
      const v = document.createElement("video");
      v.preload = "metadata";
      v.onloadedmetadata = () => resolve({ width: v.videoWidth, height: v.videoHeight, duration: v.duration });
      v.onerror = () => reject(new Error("No se pudo leer el video"));
      v.src = url;
    }
  });
