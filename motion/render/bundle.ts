import { bundle } from "@remotion/bundler";
import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";

/**
 * Bundle de Remotion cacheado en disco. Se reconstruye solo si cambio algo en
 * src/ o public/ (hash de rutas + tamanos + mtimes). El pipeline renderiza
 * decenas de piezas por dia: empaquetar en cada una costaria ~10 s.
 */

/**
 * Raiz del proyecto motion. El CLI y el panel corren con cwd = motion/; si no,
 * MOTION_ROOT o la carpeta padre de este archivo.
 */
const detectRoot = (): string => {
  if (process.env.MOTION_ROOT) return path.resolve(process.env.MOTION_ROOT);
  if (existsSync(path.join(process.cwd(), "src", "index.ts"))) return process.cwd();
  return path.resolve(__dirname, "..");
};
export const MOTION_ROOT = detectRoot();
export const BUNDLE_DIR = path.join(MOTION_ROOT, ".cache", "bundle");
const HASH_FILE = path.join(MOTION_ROOT, ".cache", "bundle.hash");

const walk = (dir: string, out: string[]) => {
  if (!existsSync(dir)) return;
  for (const name of readdirSync(dir)) {
    if (name === "_jobs" || name === "uploads" || name === "renders") continue;
    const full = path.join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) walk(full, out);
    else out.push(`${path.relative(MOTION_ROOT, full)}|${st.size}|${Math.round(st.mtimeMs)}`);
  }
};

export const sourceHash = (): string => {
  const entries: string[] = [];
  walk(path.join(MOTION_ROOT, "src"), entries);
  walk(path.join(MOTION_ROOT, "public"), entries);
  entries.push(readFileSync(path.join(MOTION_ROOT, "package.json"), "utf8"));
  return createHash("sha1").update(entries.sort().join("\n")).digest("hex");
};

export const ensureBundle = async (log: (msg: string) => void = () => undefined): Promise<string> => {
  const hash = sourceHash();
  const cached = existsSync(HASH_FILE) ? readFileSync(HASH_FILE, "utf8").trim() : "";
  if (cached === hash && existsSync(path.join(BUNDLE_DIR, "index.html"))) return BUNDLE_DIR;
  log("bundle: reconstruyendo (cambios en src/ o public/)");
  await bundle({
    entryPoint: path.join(MOTION_ROOT, "src", "index.ts"),
    outDir: BUNDLE_DIR,
    publicDir: path.join(MOTION_ROOT, "public"),
    enableCaching: true,
  });
  writeFileSync(HASH_FILE, hash);
  return BUNDLE_DIR;
};
