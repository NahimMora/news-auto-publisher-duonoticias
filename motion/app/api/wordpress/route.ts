import { NextResponse } from "next/server";
import { fetchWordPressPosts } from "../../../lib/server/wordpress";

export const runtime = "nodejs";

export async function GET() {
  try {
    return NextResponse.json(await fetchWordPressPosts(12));
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : String(err) }, { status: 502 });
  }
}
