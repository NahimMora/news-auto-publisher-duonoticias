import { NextResponse } from "next/server";
import { pieceSchema } from "../../../src/schema/piece";
import { projectStore } from "../../../lib/server/projectStore";
import { enqueueRender } from "../../../lib/server/renderJobs";

export const runtime = "nodejs";

/** Encola un render real (MP4 o PNG/JPEG) del proyecto guardado. */
export async function POST(req: Request) {
  const body = (await req.json().catch(() => ({}))) as { projectId?: string; kind?: "auto" | "mp4" | "png" | "jpeg" };
  if (!body.projectId) return NextResponse.json({ error: "Falta projectId" }, { status: 400 });
  const project = await projectStore.get(body.projectId);
  if (!project) return NextResponse.json({ error: "Proyecto inexistente" }, { status: 404 });
  const piece = pieceSchema.parse(project.piece);
  const job = enqueueRender(project.id, piece, body.kind ?? "auto");
  return NextResponse.json(job, { status: 202 });
}
