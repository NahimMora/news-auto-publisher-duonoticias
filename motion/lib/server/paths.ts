import path from "node:path";

/** Rutas de datos del panel. Todo vive en motion/data (ignorado por Git). */
export const MOTION_ROOT = process.cwd();
export const DATA_DIR = process.env.MOTION_DATA_DIR ? path.resolve(process.env.MOTION_DATA_DIR) : path.join(MOTION_ROOT, "data");
export const PROJECTS_DIR = path.join(DATA_DIR, "projects");
export const UPLOADS_DIR = path.join(DATA_DIR, "uploads");
export const RENDERS_DIR = path.join(DATA_DIR, "renders");
/** Piezas que deja el pipeline para revision (formatter/motion_engine.py). */
export const INBOX_DIR = path.join(DATA_DIR, "inbox");

/**
 * Raices desde las que el panel puede servir archivos locales. Las rutas
 * absolutas del pipeline solo se sirven si caen dentro de estas carpetas.
 */
export const allowedMediaRoots = (): string[] => {
  const roots = [DATA_DIR, path.join(MOTION_ROOT, "public")];
  const repoData = path.resolve(MOTION_ROOT, "..", "data");
  roots.push(repoData);
  return roots.map((r) => path.resolve(/*turbopackIgnore: true*/ r));
};

export const isInside = (child: string, parent: string) => {
  const rel = path.relative(parent, child);
  return !!rel && !rel.startsWith("..") && !path.isAbsolute(rel);
};
