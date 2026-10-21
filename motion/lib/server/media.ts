import { createReadStream, statSync } from "node:fs";
import path from "node:path";
import { Readable } from "node:stream";
import { allowedMediaRoots, isInside } from "./paths";

const TYPES: Record<string, string> = {
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".png": "image/png",
  ".webp": "image/webp",
  ".gif": "image/gif",
  ".mp4": "video/mp4",
  ".webm": "video/webm",
  ".mov": "video/quicktime",
  ".mp3": "audio/mpeg",
  ".m4a": "audio/mp4",
  ".wav": "audio/wav",
};

/** Sirve un archivo local con soporte de Range (el Player necesita buscar en videos). */
export const serveFile = (absPath: string, rangeHeader: string | null): Response => {
  const resolved = path.resolve(absPath);
  if (!allowedMediaRoots().some((root) => isInside(resolved, root))) {
    return new Response("Ruta no permitida", { status: 403 });
  }
  let size: number;
  try {
    size = statSync(resolved).size;
  } catch {
    return new Response("No encontrado", { status: 404 });
  }
  const type = TYPES[path.extname(resolved).toLowerCase()] ?? "application/octet-stream";
  const headers: Record<string, string> = { "Content-Type": type, "Accept-Ranges": "bytes", "Cache-Control": "no-store" };
  if (rangeHeader) {
    const m = /bytes=(\d*)-(\d*)/.exec(rangeHeader);
    if (m) {
      const start = m[1] ? parseInt(m[1], 10) : 0;
      const end = m[2] ? Math.min(parseInt(m[2], 10), size - 1) : size - 1;
      if (start <= end && start < size) {
        const stream = Readable.toWeb(createReadStream(resolved, { start, end })) as ReadableStream;
        return new Response(stream, {
          status: 206,
          headers: { ...headers, "Content-Range": `bytes ${start}-${end}/${size}`, "Content-Length": String(end - start + 1) },
        });
      }
    }
  }
  const stream = Readable.toWeb(createReadStream(resolved)) as ReadableStream;
  return new Response(stream, { status: 200, headers: { ...headers, "Content-Length": String(size) } });
};
