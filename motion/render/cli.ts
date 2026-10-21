/**
 * CLI de render para el pipeline (Python) y uso manual. No abre puertos hacia
 * afuera: el renderer sirve el bundle solo en localhost durante el render.
 *
 *   npx tsx render/cli.ts --job job.json
 *   npx tsx render/cli.ts --demo breaking --out out/demo.mp4
 *   npx tsx render/cli.ts --stdio      (worker: una peticion JSON por linea en stdin)
 *
 * job.json: { "items": [ { "piece": {...}, "out": "C:/.../x.jpg", "kind": "auto" } ] }
 * Salida: una linea JSON por evento en stdout ({"event":"done",...}).
 * Codigo de salida: 0 todo ok, 2 si alguna pieza fallo, 1 error general.
 */
import { readFileSync } from "node:fs";
import { createInterface } from "node:readline";
import { demos } from "../src/demo/pieces";
import { PieceRenderer, type RenderRequest } from "./renderPiece";

const emit = (event: Record<string, unknown>) => process.stdout.write(`${JSON.stringify(event)}\n`);

const arg = (name: string): string | undefined => {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : undefined;
};

/**
 * Modo worker para el pipeline: mantiene el bundle y el navegador calientes.
 * Entrada: {"id": "...", "piece": {...}, "out": "...", "kind": "auto"} por linea.
 * Salida: eventos JSON con el mismo id. Termina al cerrarse stdin.
 */
const stdioWorker = async () => {
  const renderer = new PieceRenderer((msg) => emit({ event: "log", msg }));
  await renderer.init();
  emit({ event: "ready" });
  const rl = createInterface({ input: process.stdin, crlfDelay: Infinity });
  for await (const line of rl) {
    const text = line.trim();
    if (!text) continue;
    let req: RenderRequest & { id?: string };
    try {
      req = JSON.parse(text);
    } catch {
      emit({ event: "error", id: null, error: "linea JSON invalida" });
      continue;
    }
    const id = req.id ?? null;
    try {
      const result = await renderer.render(req);
      emit({ event: "done", id, ...result });
    } catch (err) {
      emit({ event: "error", id, out: req.out, error: err instanceof Error ? err.message : String(err) });
    }
  }
  await renderer.close();
  process.exit(0);
};

const main = async () => {
  if (process.argv.includes("--stdio")) return stdioWorker();
  let items: RenderRequest[] = [];
  const job = arg("job");
  const demo = arg("demo");
  if (job) {
    const parsed = JSON.parse(readFileSync(job, "utf8").replace(/^\uFEFF/, ""));
    items = parsed.items ?? [];
  } else if (demo) {
    const piece = (demos as Record<string, unknown>)[demo];
    if (!piece) throw new Error(`Demo inexistente: ${demo}. Opciones: ${Object.keys(demos).join(", ")}`);
    items = [{ piece: piece as RenderRequest["piece"], out: arg("out") ?? `out/${demo}`, kind: "auto" }];
  } else {
    throw new Error("Uso: --job job.json | --demo <id> --out <archivo>");
  }

  const renderer = new PieceRenderer((msg) => emit({ event: "log", msg }));
  let failures = 0;
  try {
    for (const [index, item] of items.entries()) {
      emit({ event: "start", index, out: item.out });
      try {
        let last = -1;
        const result = await renderer.render(item, (p) => {
          const pct = Math.round(p * 100);
          if (pct >= last + 10) {
            last = pct;
            emit({ event: "progress", index, progress: pct });
          }
        });
        emit({ event: "done", index, ...result });
      } catch (err) {
        failures++;
        emit({ event: "error", index, out: item.out, error: err instanceof Error ? err.message : String(err) });
      }
    }
  } finally {
    await renderer.close();
  }
  process.exit(failures ? 2 : 0);
};

main().catch((err) => {
  emit({ event: "fatal", error: err instanceof Error ? err.message : String(err) });
  process.exit(1);
});
