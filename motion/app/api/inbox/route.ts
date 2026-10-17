import { NextResponse } from "next/server";
import { listInbox } from "../../../lib/server/projectStore";

export const runtime = "nodejs";

/** Piezas generadas por el pipeline (revision editorial). */
export async function GET() {
  return NextResponse.json(await listInbox());
}
