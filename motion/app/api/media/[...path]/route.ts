import path from "node:path";
import { DATA_DIR } from "../../../../lib/server/paths";
import { serveFile } from "../../../../lib/server/media";

export const runtime = "nodejs";
type Ctx = { params: Promise<{ path: string[] }> };

/**
 * /api/media/uploads/x.jpg, /api/media/renders/x.mp4 -> motion/data/...
 * /api/media/abs?p=C:/... -> archivo absoluto del pipeline (solo raices permitidas).
 */
export async function GET(req: Request, ctx: Ctx) {
  const { path: parts } = await ctx.params;
  const range = req.headers.get("range");
  if (parts[0] === "abs") {
    const p = new URL(req.url).searchParams.get("p") ?? "";
    return serveFile(p, range);
  }
  if (!["uploads", "renders"].includes(parts[0])) return new Response("No encontrado", { status: 404 });
  const res = serveFile(path.join(DATA_DIR, ...parts), range);
  if (parts[0] === "renders" && new URL(req.url).searchParams.has("download")) {
    res.headers.set("Content-Disposition", `attachment; filename="${parts[parts.length - 1]}"`);
  }
  return res;
}
