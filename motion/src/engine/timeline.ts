import type { Content, TemplateId } from "../schema/piece";
import { stripEmphasis } from "../design/textLayout";

/**
 * Planificador de ritmo. Reparte la duracion total en: gancho -> bloques
 * (titular, bajada, claves, cifras, cita) -> cierre. Los bloques tienen
 * minimos distintos (no todo dura lo mismo) y el sobrante se reparte con
 * pesos; en reels largos de video queda un tramo "hold" con titular compacto.
 */

export type BeatKind = "headline" | "deck" | "highlight" | "stat" | "quote" | "hold";

export type Beat = {
  kind: BeatKind;
  start: number;
  duration: number;
  /** Indice dentro de highlights/stats. */
  index: number;
  /** Foto que acompana el bloque. */
  photoIndex: number;
  /** Lista "Que se sabe": si arranca con la bajada (false cuando la bajada no entra). */
  withDeck?: boolean;
};

export type TimelinePlan = {
  hook: { start: number; duration: number };
  beats: Beat[];
  outro: { start: number; duration: number };
  total: number;
};

type Candidate = { kind: BeatKind; index: number; min: number; weight: number; withDeck?: boolean };

const readingSeconds = (text: string, base: number) => {
  // ~3.2 palabras por segundo de lectura en pantalla + tiempo de entrada.
  const words = stripEmphasis(text).split(/\s+/).filter(Boolean).length;
  return Math.max(base, 0.9 + words / 3.2);
};

export const planTimeline = (opts: {
  content: Content;
  template: TemplateId;
  fps: number;
  totalFrames: number;
  hookSeconds: number;
  outroSeconds: number;
  videoLed: boolean;
  /** El gancho de dato ya presento la primera cifra. */
  skipFirstStat?: boolean;
}): TimelinePlan => {
  const { content, template, fps, totalFrames, videoLed } = opts;
  const f = (s: number) => Math.round(s * fps);
  const hook = { start: 0, duration: f(opts.hookSeconds) };
  const outroDuration = f(opts.outroSeconds);
  const outro = { start: totalFrames - outroDuration, duration: outroDuration };
  const available = outro.start - hook.duration;

  const candidates: Candidate[] = [{ kind: "headline", index: 0, min: f(readingSeconds(content.headline, 3.4)), weight: 1.6 }];
  if (template === "data") {
    content.stats.forEach((s, i) => {
      if (i === 0 && opts.skipFirstStat && content.stats.length > 1) return;
      candidates.push({ kind: "stat", index: i, min: f(readingSeconds(s.label, 3.2)), weight: 1.2 });
    });
    if (content.deck) candidates.push({ kind: "deck", index: 0, min: f(readingSeconds(content.deck, 3.0)), weight: 1 });
  } else if (template === "breaking" && !videoLed) {
    // Urgencias: bajada y claves en una sola pantalla "Que se sabe" (lista).
    // index = cantidad de claves que entran en el tiempo disponible.
    // Si la bajada es larga y no entra, la lista se arma solo con las claves.
    const headlineMin = candidates[0].min;
    const itemSeconds = (t: string) => 0.35 + stripEmphasis(t).split(/\s+/).filter(Boolean).length / 3.6;
    const fit = (items: string[]) => {
      let count = 0;
      let need = 0;
      for (const item of items) {
        const next = need + itemSeconds(item);
        if (headlineMin + f(Math.max(3.0, 0.6 + next)) > available) break;
        need = next;
        count += 1;
      }
      return { count, need };
    };
    const withDeck = content.deck ? fit([content.deck, ...content.highlights]) : { count: 0, need: 0 };
    const onlyHighlights = fit(content.highlights);
    const useDeck = withDeck.count > 0 && withDeck.count >= onlyHighlights.count;
    const best = useDeck ? withDeck : onlyHighlights;
    if (best.count > 0) {
      const highlights = useDeck ? best.count - 1 : best.count;
      candidates.push({ kind: "deck", index: highlights, min: f(Math.max(3.0, 0.6 + best.need)), weight: 1.2, withDeck: useDeck });
    }
    if (content.quote) candidates.push({ kind: "quote", index: 0, min: f(readingSeconds(content.quote.text, 3.2)), weight: 1 });
  } else {
    if (content.deck) candidates.push({ kind: "deck", index: 0, min: f(readingSeconds(content.deck, 3.0)), weight: 1 });
    // En piezas de video el protagonista es el clip: solo titular y bajada, despues
    // queda el titular compacto ("hold") para no tapar la imagen.
    if (!videoLed) {
      content.highlights.forEach((h, i) => candidates.push({ kind: "highlight", index: i, min: f(readingSeconds(h, 2.6)), weight: 0.9 }));
      if (content.quote) candidates.push({ kind: "quote", index: 0, min: f(readingSeconds(content.quote.text, 3.2)), weight: 1 });
    }
  }

  // Entran en orden mientras alcancen los minimos.
  const chosen: Candidate[] = [];
  let used = 0;
  for (const c of candidates) {
    if (used + c.min <= available || chosen.length === 0) {
      chosen.push(c);
      used += c.min;
    }
  }

  let spare = Math.max(0, available - used);
  let holdFrames = 0;
  if (videoLed) {
    // En video largo cada bloque se estira como mucho 1.6x; el resto es "hold".
    const stretchCap = chosen.reduce((acc, c) => acc + c.min * 0.6, 0);
    if (spare > stretchCap) {
      holdFrames = spare - stretchCap;
      spare = stretchCap;
    }
  }
  const totalWeight = chosen.reduce((acc, c) => acc + c.weight, 0) || 1;

  const photos = Math.max(1, content.photos.length);
  const beats: Beat[] = [];
  let cursor = hook.duration;
  chosen.forEach((c, i) => {
    let duration = c.min + Math.floor((spare * c.weight) / totalWeight);
    if (i === chosen.length - 1 && holdFrames === 0) duration = outro.start - cursor; // cierra exacto
    beats.push({ kind: c.kind, index: c.index, start: cursor, duration, photoIndex: i % photos, withDeck: c.withDeck });
    cursor += duration;
  });
  if (holdFrames > 0) {
    beats.push({ kind: "hold", index: 0, start: cursor, duration: outro.start - cursor, photoIndex: 0 });
  }
  return { hook, beats, outro, total: totalFrames };
};
