import { NextResponse } from "next/server";
import { demos } from "../../../src/demo/pieces";
import { pieceSchema, type PieceInput } from "../../../src/schema/piece";
import { projectStore } from "../../../lib/server/projectStore";

export const runtime = "nodejs";

export async function GET() {
  return NextResponse.json(await projectStore.list());
}

/** Crea un proyecto desde una pieza, una demo (`demo`) o una plantilla vacia. */
export async function POST(req: Request) {
  const body = (await req.json().catch(() => ({}))) as { name?: string; piece?: PieceInput; demo?: keyof typeof demos; origin?: "manual" | "pipeline" | "wordpress" };
  let piece: PieceInput | undefined = body.piece;
  if (!piece && body.demo && demos[body.demo]) piece = demos[body.demo];
  if (!piece) {
    piece = {
      content: {
        id: `n-${Date.now().toString(36)}`,
        originalTitle: "Título original de la noticia",
        headline: "Escribí el titular audiovisual",
        category: "actualidad",
        date: new Date().toISOString(),
        source: { name: "Redacción Dúo" },
        editorialStatus: "draft",
      },
      presentation: { template: "editorial", format: "reel", durationSeconds: 15 },
    };
  }
  const parsed = pieceSchema.safeParse(piece);
  if (!parsed.success) return NextResponse.json({ error: "Pieza invalida", issues: parsed.error.issues }, { status: 400 });
  const project = await projectStore.create(body.name || parsed.data.content.originalTitle.slice(0, 80), parsed.data, body.origin ?? "manual");
  return NextResponse.json(project, { status: 201 });
}
