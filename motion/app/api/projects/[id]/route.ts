import { NextResponse } from "next/server";
import { pieceSchema } from "../../../../src/schema/piece";
import { projectStore } from "../../../../lib/server/projectStore";

export const runtime = "nodejs";
type Ctx = { params: Promise<{ id: string }> };

export async function GET(_req: Request, ctx: Ctx) {
  const { id } = await ctx.params;
  const project = await projectStore.get(id);
  return project ? NextResponse.json(project) : NextResponse.json({ error: "No encontrado" }, { status: 404 });
}

export async function PUT(req: Request, ctx: Ctx) {
  const { id } = await ctx.params;
  const body = (await req.json().catch(() => ({}))) as { name?: string; piece?: unknown };
  let piece;
  if (body.piece !== undefined) {
    const parsed = pieceSchema.safeParse(body.piece);
    if (!parsed.success) return NextResponse.json({ error: "Pieza invalida", issues: parsed.error.issues }, { status: 400 });
    piece = parsed.data;
  }
  const project = await projectStore.update(id, { name: body.name, piece });
  return project ? NextResponse.json(project) : NextResponse.json({ error: "No encontrado" }, { status: 404 });
}

export async function DELETE(_req: Request, ctx: Ctx) {
  const { id } = await ctx.params;
  return (await projectStore.remove(id)) ? new NextResponse(null, { status: 204 }) : NextResponse.json({ error: "No encontrado" }, { status: 404 });
}
