import React, { useEffect, useState } from "react";
import { useDelayRender } from "remotion";
import { loadBrandFonts } from "../design/fonts";

/**
 * Bloquea el render hasta que las tipografias esten cargadas: la composicion
 * de titulares mide con las fuentes reales y no puede medir con un fallback.
 */
export const FontGate: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { delayRender, continueRender, cancelRender } = useDelayRender();
  const [handle] = useState(() => delayRender("Cargando tipografias de marca"));
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let alive = true;
    loadBrandFonts()
      .then(() => {
        if (!alive) return;
        setReady(true);
        continueRender(handle);
      })
      .catch((err) => cancelRender(err));
    return () => {
      alive = false;
    };
  }, [handle, continueRender, cancelRender]);
  return ready ? <>{children}</> : null;
};
