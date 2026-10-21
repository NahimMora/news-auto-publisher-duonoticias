/**
 * Valida piezas contra el esquema Zod del motor (contrato Python -> motion).
 *   echo '{"content":{...},"presentation":{...}}' | npx tsx render/validate.ts
 * Salida: {"ok":true} o {"ok":false,"issues":[...]}; codigo 0/3.
 */
import { pieceSchema } from "../src/schema/piece";

const chunks: Buffer[] = [];
process.stdin.on("data", (c: Buffer) => chunks.push(c));
process.stdin.on("end", () => {
  try {
    const input = JSON.parse(Buffer.concat(chunks).toString("utf8").replace(/^﻿/, ""));
    const items = Array.isArray(input) ? input : [input];
    const issues: string[] = [];
    items.forEach((item, i) => {
      const parsed = pieceSchema.safeParse(item);
      if (!parsed.success) for (const issue of parsed.error.issues) issues.push(`[${i}] ${issue.path.join(".")}: ${issue.message}`);
    });
    process.stdout.write(JSON.stringify(issues.length ? { ok: false, issues } : { ok: true }) + "\n");
    process.exit(issues.length ? 3 : 0);
  } catch (err) {
    process.stdout.write(JSON.stringify({ ok: false, issues: [String(err)] }) + "\n");
    process.exit(3);
  }
});
