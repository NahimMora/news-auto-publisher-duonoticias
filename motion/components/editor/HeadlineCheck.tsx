"use client";

import React, { useEffect, useMemo, useState } from "react";
import { loadBrandFonts } from "../../src/design/fonts";
import { getLayout } from "../../src/design/layout";
import { fitTextBlock, stripEmphasis, suggestShorterHeadline } from "../../src/design/textLayout";
import { textRoles } from "../../src/design/tokens";
import type { Piece } from "../../src/schema/piece";

/**
 * Verifica en vivo si el titular entra en la composicion (misma medicion que
 * el render). Si no entra, propone una version mas corta SIN reescribir: solo
 * corta en la primera clausula. La decision es del editor.
 */
export const HeadlineCheck: React.FC<{ piece: Piece; onApply: (headline: string) => void }> = ({ piece, onApply }) => {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    loadBrandFonts().then(() => setReady(true));
  }, []);
  const { presentation, content } = piece;
  const result = useMemo(() => {
    if (!ready) return null;
    const layout = getLayout(presentation.format);
    const role = presentation.template === "breaking" ? textRoles.breakingHeadline : presentation.template === "editorial" ? textRoles.editorialHeadline : textRoles.postHeadline;
    const block = fitTextBlock({
      text: content.headline,
      role,
      maxWidth: layout.contentWidth,
      maxLines: layout.type.headlineLines,
      preferLines: layout.type.headlinePrefer,
      minSize: layout.type.headlineMin,
      maxSize: layout.type.headlineMax,
      maxHeight: layout.height * 0.34,
      emphasisItalic: role === textRoles.editorialHeadline,
    });
    return { block, chars: stripEmphasis(content.headline).length };
  }, [ready, presentation.format, presentation.template, content.headline]);

  if (!result) return null;
  const { block, chars } = result;
  const suggestion = block.overflow ? suggestShorterHeadline(content.headline, 70) : null;
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10.5px] uppercase tracking-wider">
      <span className="text-mute">{chars} caracteres</span>
      <span className="text-mute">
        {block.lines.length} líneas · {block.fontSize}px
      </span>
      {block.overflow ? <span className="text-signal">No entra completo: acortá el titular audiovisual</span> : <span className="text-amber">Entra completo</span>}
      {suggestion ? (
        <button type="button" onClick={() => onApply(suggestion)} className="normal-case tracking-normal text-white underline decoration-amber underline-offset-2">
          Sugerencia: “{suggestion}”
        </button>
      ) : null}
    </div>
  );
};
