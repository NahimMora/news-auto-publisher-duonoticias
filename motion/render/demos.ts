/**
 * Renderiza todas las piezas de demostracion a out/demos/.
 *   npm run render:demos
 */
import path from "node:path";
import { demos } from "../src/demo/pieces";
import { PieceRenderer } from "./renderPiece";

const main = async () => {
  const renderer = new PieceRenderer((m) => console.log(m));
  const outDir = path.join(process.cwd(), "out", "demos");
  try {
    for (const [name, piece] of Object.entries(demos)) {
      const still = piece.presentation.template === "static";
      const out = path.join(outDir, `${name}.${still ? "jpg" : "mp4"}`);
      const result = await renderer.render({ piece, out, kind: still ? "jpeg" : "mp4" });
      console.log(`${name.padEnd(16)} ${result.width}x${result.height} ${(result.durationInFrames / 30).toFixed(1)}s ${(result.ms / 1000).toFixed(1)}s -> ${result.out}`);
    }
  } finally {
    await renderer.close();
  }
};

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
