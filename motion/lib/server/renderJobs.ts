import { mkdir } from "node:fs/promises";
import path from "node:path";
import { PieceRenderer, type RenderKind } from "../../render/renderPiece";
import { pieceSchema, type PieceInput } from "../../src/schema/piece";
import { isStillTemplate } from "../../src/templates/meta";
import { DATA_DIR, RENDERS_DIR } from "./paths";

/**
 * Cola de render en proceso (una pieza por vez, navegador reutilizado).
 * Suficiente para un panel local de redaccion; se reemplaza por un worker si
 * hiciera falta escalar.
 */

export type RenderJob = {
  id: string;
  projectId: string;
  kind: Exclude<RenderKind, "auto"> | "auto";
  status: "queued" | "bundling" | "rendering" | "done" | "error";
  progress: number;
  file?: string;
  error?: string;
  createdAt: number;
  ms?: number;
};

type Queue = { jobs: Map<string, RenderJob>; chain: Promise<void>; renderer: PieceRenderer | null };

const g = globalThis as unknown as { __duoRenderQueue?: Queue };
const queue: Queue = g.__duoRenderQueue ?? { jobs: new Map(), chain: Promise.resolve(), renderer: null };
g.__duoRenderQueue = queue;

export const getJob = (id: string) => queue.jobs.get(id) ?? null;

export const enqueueRender = (projectId: string, piece: PieceInput, kind: RenderJob["kind"]): RenderJob => {
  const id = `r-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
  const job: RenderJob = { id, projectId, kind, status: "queued", progress: 0, createdAt: Date.now() };
  queue.jobs.set(id, job);
  queue.chain = queue.chain.then(async () => {
    try {
      job.status = "bundling";
      if (!queue.renderer) queue.renderer = new PieceRenderer();
      await queue.renderer.init();
      job.status = "rendering";
      await mkdir(RENDERS_DIR, { recursive: true });
      // La extension sale del tipo pedido o, en "auto", de la plantilla (video o post).
      const still = isStillTemplate(pieceSchema.parse(piece).presentation.template);
      const ext = kind === "png" ? "png" : kind === "jpeg" ? "jpg" : kind === "mp4" ? "mp4" : still ? "jpg" : "mp4";
      const file = path.join(RENDERS_DIR, `${projectId}-${id}.${ext}`);
      const result = await queue.renderer.render({ piece, out: file, kind, assetRoots: [DATA_DIR] }, (p) => {
        job.progress = p;
      });
      job.file = path.basename(file);
      job.ms = result.ms;
      job.progress = 1;
      job.status = "done";
    } catch (err) {
      job.status = "error";
      job.error = err instanceof Error ? err.message : String(err);
    }
  });
  return job;
};
