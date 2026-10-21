import { copyFileSync, existsSync, mkdirSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { Piece } from "../src/schema/piece";

/**
 * Las piezas pueden apuntar a archivos locales (rutas absolutas del pipeline o
 * subidas del panel). El navegador del renderer solo ve lo que sirve el
 * bundle, asi que se copian a `<bundle>/public/_jobs/<job>/` y se reescriben
 * como rutas relativas (staticFile) solo para este render.
 */

const isRemote = (src: string) => /^(https?:|data:|blob:)/i.test(src);

const localPathOf = (src: string, extraRoots: string[]): string | null => {
  if (isRemote(src)) return null;
  const candidate = src.startsWith("file:") ? fileURLToPath(src) : src;
  if (path.isAbsolute(candidate) && existsSync(candidate)) return candidate;
  for (const root of extraRoots) {
    const p = path.join(root, candidate);
    if (existsSync(p)) return p;
  }
  return null;
};

export type StagedPiece = { piece: Piece; cleanup: () => void };

export const stagePieceAssets = (piece: Piece, bundleDir: string, jobId: string, extraRoots: string[] = []): StagedPiece => {
  const jobDir = path.join(bundleDir, "public", "_jobs", jobId);
  let counter = 0;
  const stage = (src: string): string => {
    // Ya presente en public/ del bundle (demo/, brand/...): no se toca.
    if (!path.isAbsolute(src) && !src.startsWith("file:") && existsSync(path.join(bundleDir, "public", src))) return src;
    const local = localPathOf(src, extraRoots);
    if (!local) return src;
    mkdirSync(jobDir, { recursive: true });
    const name = `${String(counter++).padStart(2, "0")}-${path.basename(local).replace(/[^\w.-]+/g, "_")}`;
    copyFileSync(local, path.join(jobDir, name));
    return `_jobs/${jobId}/${name}`;
  };
  const c = piece.content;
  const staged: Piece = {
    ...piece,
    content: {
      ...c,
      photos: c.photos.map((p) => ({ ...p, src: stage(p.src) })),
      videos: c.videos.map((v) => ({ ...v, src: stage(v.src) })),
    },
    presentation: {
      ...piece.presentation,
      audio: piece.presentation.audio ? { ...piece.presentation.audio, src: stage(piece.presentation.audio.src) } : undefined,
    },
  };
  return {
    piece: staged,
    cleanup: () => {
      if (existsSync(jobDir)) rmSync(jobDir, { recursive: true, force: true });
    },
  };
};
