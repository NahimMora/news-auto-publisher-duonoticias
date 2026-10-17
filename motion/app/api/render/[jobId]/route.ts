import { NextResponse } from "next/server";
import { getJob } from "../../../../lib/server/renderJobs";

export const runtime = "nodejs";
type Ctx = { params: Promise<{ jobId: string }> };

export async function GET(_req: Request, ctx: Ctx) {
  const { jobId } = await ctx.params;
  const job = getJob(jobId);
  return job ? NextResponse.json(job) : NextResponse.json({ error: "Trabajo inexistente" }, { status: 404 });
}
