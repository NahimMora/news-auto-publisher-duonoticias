import React, { useMemo } from "react";
import { AbsoluteFill, useVideoConfig } from "remotion";
import { brand } from "../brand/brand.config";
import { getCategory } from "../brand/categories";
import { BrandLogo } from "../components/brand";
import { FontGate } from "../components/FontGate";
import { fitTextBlock } from "../design/textLayout";
import { roleStyle, textRoles, upper } from "../design/tokens";
import { TextReveal } from "../engine/animations/TextReveal";
import { BrandFrame, CategoryChip, extraOf, fmtNum, Photo, SectionHead, SourceLine, T, WeatherIcon, type Extra } from "./formatKit";
import type { TemplateProps } from "./shared";

/**
 * G · TABLERO DE SERVICIO Y RESUMEN (still 4:5 o 9:16). Una pieza por
 * `content.extra.kind`:
 * - digest-cover / digest-item / digest-close: carrusel "Lo que tenés que saber hoy" (8 h).
 * - weather: clima y alertas del SMN.  - dollar: cotizaciones.
 * - holidays: proximos feriados.       - services: agua, luz y pasos fronterizos.
 * Todos los datos salen de fuentes oficiales o de notas ya publicadas.
 */

type Box = { W: number; H: number; u: number; m: number; top: number; bottom: number; story: boolean };

const useBox = (): Box => {
  const { width: W, height: H } = useVideoConfig();
  const u = W / 1080;
  const story = H / W > 1.6;
  return { W, H, u, m: Math.round(76 * u), top: Math.round((story ? 270 : 70) * u), bottom: Math.round((story ? 1650 : 1280) * u), story };
};

const Footer: React.FC<{ box: Box; source: string; index?: number; total?: number }> = ({ box, source, index, total }) => (
  <div style={{ position: "absolute", left: box.m, right: box.m, top: box.bottom - 52 * box.u, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 20 * box.u }}>
    <SourceLine text={source} size={Math.round(20 * box.u)} />
    {total && total > 1 ? (
      <span style={{ ...roleStyle(textRoles.meta, Math.round(22 * box.u)), color: brand.colors.accent }}>
        {index}/{total}
      </span>
    ) : (
      <span style={{ ...roleStyle(textRoles.meta, Math.round(20 * box.u)), color: "rgba(255,255,255,0.7)" }}>{brand.handle}</span>
    )}
  </div>
);

const Logo: React.FC<{ box: Box }> = ({ box }) => (
  <div style={{ position: "absolute", right: box.m, top: box.top + 6 * box.u }}>
    <BrandLogo height={Math.round(46 * box.u)} />
  </div>
);

// ---------- Lo que tenes que saber hoy ----------

const DigestCover: React.FC<{ x: Extra; box: Box }> = ({ x, box }) => {
  const { u, m } = box;
  const w = x.weather as { temp: number; min: number; max: number; desc: string; rain: number } | undefined;
  const items = (x.items as { headline: string; category: string }[]) ?? [];
  return (
    <BrandFrame corners={0.09}>
      <Logo box={box} />
      <div style={{ position: "absolute", left: m, right: m, top: box.top, bottom: box.H - box.bottom + 90 * u, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
        <span style={{ ...roleStyle(textRoles.meta, Math.round(24 * u)), color: brand.colors.accent }}>{upper(String(x.dateLabel ?? ""))}</span>
        <T role={textRoles.breakingHeadline} size={Math.round(118 * u)}>
          Lo que tenés que saber <span style={{ color: brand.colors.accent }}>hoy</span>
        </T>
        {w ? (
          <div style={{ display: "flex", alignItems: "center", gap: 22 * u, padding: `${18 * u}px ${24 * u}px`, background: "rgba(255,255,255,0.08)", borderLeft: `${6 * u}px solid ${brand.colors.accent}`, marginTop: 10 * u }}>
            <WeatherIcon desc={w.desc} size={Math.round(84 * u)} />
            <div style={{ display: "flex", flexDirection: "column", gap: 6 * u }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 18 * u }}>
                <span style={{ ...roleStyle(textRoles.dataNumber, Math.round(72 * u)), color: brand.colors.white }}>{fmtNum(w.temp, 0)}°</span>
                <span style={{ ...roleStyle(textRoles.meta, Math.round(22 * u)), color: "rgba(255,255,255,0.8)" }}>
                  MÍN {fmtNum(w.min)}° · MÁX {fmtNum(w.max)}°
                </span>
              </div>
              <span style={{ ...roleStyle(textRoles.deck, Math.round(26 * u)), whiteSpace: "normal", color: "rgba(255,255,255,0.86)" }}>
                Salta · {w.desc} · lluvia {w.rain}%
              </span>
            </div>
          </div>
        ) : null}
        <div style={{ display: "flex", flexDirection: "column", gap: 0, marginTop: 18 * u }}>
          {items.map((it, i) => (
            <div key={i} style={{ display: "flex", gap: 24 * u, alignItems: "center", padding: `${24 * u}px 0`, borderTop: i ? "1px solid rgba(255,255,255,0.14)" : "none" }}>
              <span style={{ ...roleStyle(textRoles.dataNumber, Math.round(66 * u)), color: getCategory(it.category).accent, width: 52 * u, flex: "none" }}>{i + 1}</span>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 * u, minWidth: 0 }}>
                <span style={{ ...roleStyle(textRoles.kicker, Math.round(18 * u)), color: getCategory(it.category).accent }}>{upper(getCategory(it.category).label)}</span>
                <T role={textRoles.deckStrong} size={Math.round(33 * u)} lines={2}>
                  {it.headline.replace(/\*/g, "")}
                </T>
              </div>
            </div>
          ))}
        </div>
      </div>
      <div style={{ position: "absolute", left: m, right: m, top: box.bottom - 52 * u, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <SourceLine text="Clima: SMN" size={Math.round(20 * u)} />
        <span style={{ ...roleStyle(textRoles.kicker, Math.round(22 * u)), color: brand.colors.accent }}>DESLIZÁ →</span>
      </div>
    </BrandFrame>
  );
};

const DigestItem: React.FC<{ x: Extra; box: Box }> = ({ x, box }) => {
  const { u, m, W } = box;
  const photoH = Math.round((box.story ? 900 : 700) * u);
  const points = ((x.points as string[]) ?? []).slice(0, 3);
  const block = useMemo(
    () =>
      fitTextBlock({
        text: String(x.headline ?? ""),
        role: textRoles.postHeadline,
        maxWidth: W - m * 2,
        maxLines: 4,
        preferLines: 3,
        minSize: Math.round(48 * u),
        maxSize: Math.round(72 * u),
        maxHeight: 300 * u,
      }),
    [x.headline, W, m, u],
  );
  return (
    <BrandFrame corners={0}>
      <AbsoluteFill style={{ overflow: "hidden" }}>
        <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: photoH + 260 * u }}>
          <Photo src={x.photo as string} />
        </div>
        <AbsoluteFill style={{ background: `linear-gradient(to bottom, rgba(30,13,51,0.45) 0%, rgba(30,13,51,0) 18%, rgba(30,13,51,0) ${Math.round((photoH / box.H) * 100) - 22}%, rgba(30,13,51,0.92) ${Math.round((photoH / box.H) * 100) + 6}%, ${brand.colors.primaryDeep} ${Math.round(((photoH + 240 * u) / box.H) * 100)}%)` }} />
      </AbsoluteFill>
      <div style={{ position: "absolute", left: m, top: box.top - 10 * u }}>
        <span style={{ ...roleStyle(textRoles.dataNumber, Math.round(130 * u)), color: brand.colors.accent, textShadow: "0 4px 24px rgba(0,0,0,0.5)" }}>{String(x.n)}</span>
      </div>
      <Logo box={box} />
      <div style={{ position: "absolute", left: m, right: m, bottom: box.H - box.bottom + 90 * u, display: "flex", flexDirection: "column", gap: 24 * u }}>
        <CategoryChip category={x.category as string} size={Math.round(24 * u)} />
        <TextReveal layout={block} role={textRoles.postHeadline} color={brand.colors.white} accent={brand.colors.accent} mode="none" emphasisStyle="marker" markerTextColor={brand.colors.ink} />
        {points.length ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 * u, marginTop: 4 * u }}>
            {points.map((pt) => (
              <div key={pt} style={{ display: "flex", gap: 16 * u, alignItems: "center" }}>
                <span style={{ width: 14 * u, height: 14 * u, background: brand.colors.accent, flex: "none", rotate: "45deg" }} />
                <T role={textRoles.deck} size={Math.round(31 * u)} color="rgba(255,255,255,0.92)" lines={1}>
                  {pt}
                </T>
              </div>
            ))}
          </div>
        ) : null}
      </div>
      <Footer box={box} source={`Fuente: ${x.source}`} index={x.slide as number} total={x.total as number} />
    </BrandFrame>
  );
};

const DigestClose: React.FC<{ x: Extra; box: Box }> = ({ x, box }) => {
  const { u, m } = box;
  const d = x.dollar as { name: string; sell: number }[] | undefined;
  const h = x.holiday as { name: string; dateLabel: string; daysLeft: number } | undefined;
  return (
    <BrandFrame corners={0.14}>
      <div style={{ position: "absolute", left: m, right: m, top: box.top, bottom: box.H - box.bottom + 90 * u, display: "flex", flexDirection: "column", justifyContent: "center", gap: 34 * u }}>
        <T role={textRoles.breakingHeadline} size={Math.round(96 * u)}>
          Y además…
        </T>
        {d ? (
          <div style={{ display: "flex", gap: 18 * u }}>
            {d.map((q) => (
              <div key={q.name} style={{ flex: 1, padding: `${20 * u}px ${22 * u}px`, background: "rgba(255,255,255,0.08)", display: "flex", flexDirection: "column", gap: 8 * u }}>
                <span style={{ ...roleStyle(textRoles.kicker, Math.round(22 * u)), color: brand.colors.accent }}>DÓLAR {upper(q.name)}</span>
                <span style={{ ...roleStyle(textRoles.dataNumber, Math.round(72 * u)), color: brand.colors.white }}>${fmtNum(q.sell)}</span>
              </div>
            ))}
          </div>
        ) : null}
        {h ? (
          <div style={{ padding: `${20 * u}px ${22 * u}px`, background: "rgba(255,255,255,0.08)", display: "flex", flexDirection: "column", gap: 8 * u }}>
            <span style={{ ...roleStyle(textRoles.kicker, Math.round(22 * u)), color: brand.colors.accent }}>PRÓXIMO FERIADO · EN {h.daysLeft} DÍAS</span>
            <T role={textRoles.deckStrong} size={Math.round(38 * u)}>
              {h.dateLabel}: {h.name}
            </T>
          </div>
        ) : null}
        <div style={{ display: "flex", alignItems: "center", gap: 24 * u, marginTop: 40 * u }}>
          <BrandLogo height={Math.round(70 * u)} />
        </div>
        <T role={textRoles.deck} size={Math.round(32 * u)} color="rgba(255,255,255,0.86)">
          Todos los días a las 8, lo más importante de Salta en un solo posteo. Activá las notificaciones de {brand.handle}.
        </T>
      </div>
      <Footer box={box} source="Dólar: DolarApi · Feriados: ArgentinaDatos" index={x.n as number} total={x.total as number} />
    </BrandFrame>
  );
};

// ---------- Servicios ----------

const ALERT = [
  { label: "Sin alertas del SMN", color: "#2ED394", text: brand.colors.ink },
  { label: "Sin alertas del SMN", color: "#2ED394", text: brand.colors.ink },
  { label: "Alerta amarilla", color: "#FFD400", text: brand.colors.ink },
  { label: "Alerta naranja", color: "#FF8A00", text: brand.colors.ink },
  { label: "Alerta roja", color: brand.colors.signal, text: brand.colors.white },
];

const Weather: React.FC<{ x: Extra; box: Box }> = ({ x, box }) => {
  const { u, m } = box;
  const now = x.now as { temp: number; desc: string; humidity: number; wind: string; time: string };
  const days = (x.days as { label: string; min: number; max: number; desc: string; rain: number }[]) ?? [];
  const level = Math.min(4, Math.max(1, Number(x.alertLevel ?? 1)));
  const a = ALERT[level];
  return (
    <BrandFrame corners={0.08}>
      <Logo box={box} />
      <div style={{ position: "absolute", left: m, right: m, top: box.top, bottom: box.H - box.bottom + 100 * u, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
        <SectionHead label="El tiempo en Salta" size={Math.round(26 * u)} color="#6CC9FF" />
        <div style={{ display: "flex", alignItems: "center", gap: 30 * u, marginTop: 10 * u }}>
          <WeatherIcon desc={now.desc} size={Math.round(190 * u)} />
          <div style={{ display: "flex", flexDirection: "column", gap: 8 * u }}>
            <span style={{ ...roleStyle(textRoles.dataNumber, Math.round(190 * u)), color: brand.colors.white }}>{fmtNum(now.temp, 0)}°</span>
            <span style={{ ...roleStyle(textRoles.meta, Math.round(22 * u)), color: "rgba(255,255,255,0.75)" }}>{upper(`Ahora · ${now.time} h`)}</span>
          </div>
        </div>
        <T role={textRoles.deckStrong} size={Math.round(40 * u)}>
          {now.desc}
        </T>
        <span style={{ ...roleStyle(textRoles.meta, Math.round(22 * u)), whiteSpace: "normal", color: "rgba(255,255,255,0.78)" }}>
          {upper(`Humedad ${fmtNum(now.humidity)}% · Viento ${now.wind}`)}
        </span>
        <div style={{ display: "flex", alignItems: "center", gap: 16 * u, padding: `${14 * u}px ${20 * u}px`, background: a.color, alignSelf: "flex-start" }}>
          <span style={{ ...roleStyle(textRoles.kicker, Math.round(24 * u)), color: a.text }}>{upper(a.label)}</span>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: `repeat(${days.length}, 1fr)`, gap: 14 * u, marginTop: 8 * u }}>
          {days.map((d) => (
            <div key={d.label} style={{ background: "rgba(255,255,255,0.08)", padding: `${18 * u}px ${12 * u}px`, display: "flex", flexDirection: "column", alignItems: "center", gap: 10 * u }}>
              <span style={{ ...roleStyle(textRoles.kicker, Math.round(20 * u)), color: brand.colors.accent }}>{upper(d.label)}</span>
              <WeatherIcon desc={d.desc} size={Math.round(70 * u)} />
              <span style={{ ...roleStyle(textRoles.dataNumber, Math.round(40 * u)), color: brand.colors.white }}>
                {fmtNum(d.max)}°<span style={{ opacity: 0.6, fontSize: 28 * u }}> {fmtNum(d.min)}°</span>
              </span>
              <span style={{ ...roleStyle(textRoles.meta, Math.round(17 * u)), color: "#6CC9FF" }}>💧 {d.rain}%</span>
            </div>
          ))}
        </div>
      </div>
      <Footer box={box} source="Fuente: Servicio Meteorológico Nacional" />
    </BrandFrame>
  );
};

const Dollar: React.FC<{ x: Extra; box: Box }> = ({ x, box }) => {
  const { u, m } = box;
  const quotes = (x.quotes as { name: string; buy?: number; sell: number; prev?: number }[]) ?? [];
  return (
    <BrandFrame corners={0.08}>
      <Logo box={box} />
      <div style={{ position: "absolute", left: m, right: m, top: box.top, bottom: box.H - box.bottom + 100 * u, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
        <SectionHead label="Dólar hoy" size={Math.round(26 * u)} color="#2ED394" />
        <T role={textRoles.breakingHeadline} size={Math.round(96 * u)}>
          {String(x.title ?? "")}
        </T>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 * u }}>
          {quotes.map((q) => {
            const delta = q.prev ? q.sell - q.prev : 0;
            const color = delta > 0 ? "#FF6A3D" : delta < 0 ? "#2ED394" : "rgba(255,255,255,0.6)";
            return (
              <div key={q.name} style={{ display: "flex", alignItems: "center", gap: 20 * u, padding: `${26 * u}px ${24 * u}px`, background: "rgba(255,255,255,0.08)" }}>
                <span style={{ ...roleStyle(textRoles.kicker, Math.round(30 * u)), color: brand.colors.accent, width: 200 * u }}>{upper(q.name)}</span>
                <span style={{ ...roleStyle(textRoles.meta, Math.round(20 * u)), color: "rgba(255,255,255,0.7)", flex: 1 }}>{q.buy ? `COMPRA $${fmtNum(q.buy)}` : ""}</span>
                <span style={{ ...roleStyle(textRoles.dataNumber, Math.round(80 * u)), color: brand.colors.white }}>${fmtNum(q.sell, q.sell % 1 ? 1 : 0)}</span>
                <span style={{ ...roleStyle(textRoles.meta, Math.round(20 * u)), color, width: 110 * u, textAlign: "right" }}>
                  {q.prev ? `${delta > 0 ? "▲" : delta < 0 ? "▼" : "="} ${fmtNum(Math.abs(delta))}` : ""}
                </span>
              </div>
            );
          })}
        </div>
        <span style={{ ...roleStyle(textRoles.meta, Math.round(19 * u)), whiteSpace: "normal", color: "rgba(255,255,255,0.65)" }}>{upper(`Valores de venta · ${x.updated ?? ""} · variación contra el cierre anterior`)}</span>
      </div>
      <Footer box={box} source="Fuente: DolarApi / BCRA" />
    </BrandFrame>
  );
};

const Holidays: React.FC<{ x: Extra; box: Box }> = ({ x, box }) => {
  const { u, m } = box;
  const next = x.next as { name: string; dateLabel: string; daysLeft: number; type: string };
  const more = (x.more as { name: string; dateLabel: string; type: string }[]) ?? [];
  return (
    <BrandFrame corners={0.12}>
      <Logo box={box} />
      <div style={{ position: "absolute", left: m, right: m, top: box.top, bottom: box.H - box.bottom + 100 * u, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
        <SectionHead label="Próximo feriado" size={Math.round(26 * u)} />
        <div style={{ display: "flex", alignItems: "baseline", gap: 20 * u, marginTop: 30 * u }}>
          <span style={{ ...roleStyle(textRoles.dataNumber, Math.round(330 * u)), color: brand.colors.accent }}>{next.daysLeft}</span>
          <span style={{ ...roleStyle(textRoles.breakingHeadline, Math.round(70 * u)), color: brand.colors.white }}>DÍAS</span>
        </div>
        <T role={textRoles.postHeadline} size={Math.round(64 * u)}>
          {next.name}
        </T>
        <span style={{ ...roleStyle(textRoles.kicker, Math.round(28 * u)), color: "rgba(255,255,255,0.86)" }}>{upper(`${next.dateLabel} · feriado ${next.type}`)}</span>
        <div style={{ display: "flex", flexDirection: "column", gap: 14 * u }}>
          <span style={{ ...roleStyle(textRoles.meta, Math.round(22 * u)), color: brand.colors.accent }}>DESPUÉS</span>
          {more.map((h) => (
            <div key={h.name + h.dateLabel} style={{ display: "flex", gap: 20 * u, padding: `${22 * u}px ${22 * u}px`, background: "rgba(255,255,255,0.08)" }}>
              <span style={{ ...roleStyle(textRoles.kicker, Math.round(24 * u)), color: brand.colors.accent, width: 230 * u, flex: "none" }}>{upper(h.dateLabel)}</span>
              <T role={textRoles.deckStrong} size={Math.round(28 * u)}>
                {h.name}
              </T>
            </div>
          ))}
        </div>
      </div>
      <Footer box={box} source="Fuente: calendario oficial (ArgentinaDatos)" />
    </BrandFrame>
  );
};

const StatusRow: React.FC<{ u: number; icon: string; title: string; ok: boolean | null; text: string }> = ({ u, icon, title, ok, text }) => (
  <div style={{ display: "flex", gap: 22 * u, padding: `${28 * u}px ${24 * u}px`, background: "rgba(255,255,255,0.08)", alignItems: "flex-start" }}>
    <span style={{ fontSize: 50 * u, lineHeight: 1 }}>{icon}</span>
    <div style={{ display: "flex", flexDirection: "column", gap: 8 * u, flex: 1 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14 * u }}>
        <span style={{ ...roleStyle(textRoles.kicker, Math.round(26 * u)), color: brand.colors.white }}>{upper(title)}</span>
        <span style={{ ...roleStyle(textRoles.meta, Math.round(18 * u)), padding: `${5 * u}px ${10 * u}px`, background: ok === null ? "rgba(255,255,255,0.2)" : ok ? "#2ED394" : brand.colors.signal, color: ok === null ? "#fff" : brand.colors.ink }}>
          {ok === null ? "SIN DATOS" : ok ? "NORMAL" : "AFECTADO"}
        </span>
      </div>
      <T role={textRoles.deck} size={Math.round(30 * u)} color="rgba(255,255,255,0.86)">
        {text}
      </T>
    </div>
  </div>
);

const Services: React.FC<{ x: Extra; box: Box }> = ({ x, box }) => {
  const { u, m } = box;
  const water = x.water as { ok: boolean | null; text: string };
  const power = x.power as { ok: boolean | null; text: string };
  const passes = (x.passes as { name: string; country: string; state: string }[]) ?? [];
  return (
    <BrandFrame corners={0.08}>
      <Logo box={box} />
      <div style={{ position: "absolute", left: m, right: m, top: box.top, bottom: box.H - box.bottom + 100 * u, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
        <SectionHead label="Servicios hoy" date={String(x.dateLabel ?? "")} size={Math.round(26 * u)} />
        <T role={textRoles.breakingHeadline} size={Math.round(88 * u)}>
          Agua, luz y pasos: cómo está Salta
        </T>
        <StatusRow u={u} icon="🚰" title="Agua · Aguas del Norte" ok={water.ok} text={water.text} />
        <StatusRow u={u} icon="💡" title="Luz · EDESA" ok={power.ok} text={power.text} />
        <div style={{ padding: `${26 * u}px ${24 * u}px`, background: "rgba(255,255,255,0.08)", display: "flex", flexDirection: "column", gap: 18 * u }}>
          <span style={{ ...roleStyle(textRoles.kicker, Math.round(26 * u)), color: brand.colors.white }}>🛣️  PASOS FRONTERIZOS</span>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: `${10 * u}px ${24 * u}px` }}>
            {passes.map((p) => (
              <div key={p.name} style={{ display: "flex", alignItems: "center", gap: 10 * u }}>
                <span style={{ width: 16 * u, height: 16 * u, borderRadius: "50%", flex: "none", background: p.state === "ABIERTO" ? "#2ED394" : brand.colors.signal }} />
                <span style={{ ...roleStyle(textRoles.deckStrong, Math.round(28 * u)), whiteSpace: "normal", color: brand.colors.white }}>
                  {p.name} <span style={{ opacity: 0.6, fontWeight: 470 }}>({p.country})</span>
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
      <Footer box={box} source="Fuentes: Aguas del Norte · EDESA · Min. de Seguridad" />
    </BrandFrame>
  );
};

const Unknown: React.FC<{ kind?: string }> = ({ kind }) => (
  <AbsoluteFill style={{ background: brand.colors.ink, color: "#fff", alignItems: "center", justifyContent: "center", fontSize: 40 }}>tablero desconocido: {kind}</AbsoluteFill>
);

const BoardInner: React.FC<TemplateProps> = ({ piece }) => {
  const box = useBox();
  const x = extraOf(piece.content);
  switch (x.kind) {
    case "digest-cover":
      return <DigestCover x={x} box={box} />;
    case "digest-item":
      return <DigestItem x={x} box={box} />;
    case "digest-close":
      return <DigestClose x={x} box={box} />;
    case "weather":
      return <Weather x={x} box={box} />;
    case "dollar":
      return <Dollar x={x} box={box} />;
    case "holidays":
      return <Holidays x={x} box={box} />;
    case "services":
      return <Services x={x} box={box} />;
    default:
      return <Unknown kind={x.kind} />;
  }
};

export const ServiceBoard: React.FC<TemplateProps> = ({ piece }) => (
  <FontGate>
    <BoardInner piece={piece} />
  </FontGate>
);

