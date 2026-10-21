import { openBrowser, renderMedia, renderStill, selectComposition } from "@remotion/renderer";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { pieceSchema, type Piece, type PieceInput } from "../src/schema/piece";
import { stagePieceAssets } from "./assets";
import { ensureBundle } from "./bundle";

/**
 * Render de una pieza a archivo. Video: H.264 + AAC, yuv420p, 30 fps, con pista
 * de audio siempre presente (Instagram rechaza algunos reels sin audio).
 * Estatico: JPEG (Instagram solo publica JPEG) o PNG.
 */

export type RenderKind = "auto" | "mp4" | "jpeg" | "png";

export type RenderRequest = {
  piece: PieceInput;
  out: string;
  kind?: RenderKind;
  /** Raices extra para resolver rutas relativas (ej. carpeta de subidas del panel). */
  assetRoots?: string[];
};

export type RenderResult = {
  out: string;
  kind: Exclude<RenderKind, "auto">;
  durationInFrames: number;
  width: number;
  height: number;
  template: string;
  ms: number;
};

type Browser = Awaited<ReturnType<typeof openBrowser>>;

export class PieceRenderer {
  private browser: Browser | null = null;
  private serveUrl: string | null = null;

  constructor(private readonly log: (msg: string) => void = () => undefined) {}

  async init(): Promise<void> {
    if (!this.serveUrl) this.serveUrl = await ensureBundle(this.log);
    if (!this.browser) {
      this.browser = await openBrowser("chrome", {
        chromiumOptions: { gl: "angle" },
        logLevel: "error",
      });
    }
  }

  async close(): Promise<void> {
    if (this.browser) await this.browser.close({ silent: true });
    this.browser = null;
  }

  async render(req: RenderRequest, onProgress?: (p: number) => void): Promise<RenderResult> {
    await this.init();
    const started = Date.now();
    const piece: Piece = pieceSchema.parse(req.piece);
    const jobId = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    const staged = stagePieceAssets(piece, this.serveUrl as string, jobId, req.assetRoots ?? []);
    try {
      const inputProps = { piece: staged.piece };
      const composition = await selectComposition({
        serveUrl: this.serveUrl as string,
        id: "Piece",
        inputProps,
        puppeteerInstance: this.browser ?? undefined,
        logLevel: "error",
      });
      const still = composition.durationInFrames <= 1;
      let kind: Exclude<RenderKind, "auto"> = req.kind && req.kind !== "auto" ? req.kind : still ? "jpeg" : "mp4";
      if (!still && kind !== "mp4") kind = "mp4";
      mkdirSync(path.dirname(path.resolve(req.out)), { recursive: true });
      if (kind === "mp4") {
        await renderMedia({
          composition,
          serveUrl: this.serveUrl as string,
          codec: "h264",
          outputLocation: req.out,
          inputProps,
          crf: 19,
          pixelFormat: "yuv420p",
          audioCodec: "aac",
          audioBitrate: "192k",
          enforceAudioTrack: true,
          x264Preset: "medium",
          imageFormat: "jpeg",
          jpegQuality: 92,
          puppeteerInstance: this.browser ?? undefined,
          chromiumOptions: { gl: "angle" },
          onProgress: ({ progress }) => onProgress?.(progress),
          logLevel: "error",
          overwrite: true,
        });
      } else {
        await renderStill({
          composition,
          serveUrl: this.serveUrl as string,
          output: req.out,
          inputProps,
          frame: 0,
          imageFormat: kind,
          jpegQuality: 93,
          puppeteerInstance: this.browser ?? undefined,
          chromiumOptions: { gl: "angle" },
          logLevel: "error",
          overwrite: true,
        });
        onProgress?.(1);
      }
      return {
        out: path.resolve(req.out),
        kind,
        durationInFrames: composition.durationInFrames,
        width: composition.width,
        height: composition.height,
        template: piece.presentation.template,
        ms: Date.now() - started,
      };
    } finally {
      staged.cleanup();
    }
  }
}
