import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { NextResponse } from "next/server";
import { UPLOADS_DIR } from "../../../lib/server/paths";

export const runtime = "nodejs";

const ALLOWED = /\.(jpe?g|png|webp|mp4|mov|webm|mp3|m4a|wav)$/i;
const MAX_BYTES = 300 * 1024 * 1024;

/** Sube una foto/video/audio local. Devuelve la ruta relativa para la pieza. */
export async function POST(req: Request) {
  const form = await req.formData();
  const file = form.get("file");
  if (!(file instanceof File)) return NextResponse.json({ error: "Falta el archivo" }, { status: 400 });
  if (!ALLOWED.test(file.name)) return NextResponse.json({ error: "Formato no admitido" }, { status: 415 });
  if (file.size > MAX_BYTES) return NextResponse.json({ error: "Archivo demasiado grande" }, { status: 413 });
  await mkdir(UPLOADS_DIR, { recursive: true });
  const safe = file.name.replace(/[^\w.-]+/g, "_").slice(-80);
  const name = `${Date.now().toString(36)}-${safe}`;
  await writeFile(path.join(UPLOADS_DIR, name), Buffer.from(await file.arrayBuffer()));
  return NextResponse.json({ src: `uploads/${name}`, name: file.name, size: file.size });
}
