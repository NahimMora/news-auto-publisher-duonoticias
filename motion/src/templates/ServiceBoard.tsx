import React, { useMemo } from "react";
import { AbsoluteFill, useVideoConfig } from "remotion";
import { brand } from "../brand/brand.config";
import { getCategory } from "../brand/categories";
import { BrandLogo } from "../components/brand";
import { FontGate } from "../components/FontGate";
import { fitTextBlock } from "../design/textLayout";
import { roleStyle, textRoles, upper } from "../design/tokens";
import { TextReveal } from "../engine/animations/TextReveal";
import { slashCorner } from "../engine/animations/geometry";
import { BrandFrame, CategoryChip, extraOf, fmtNum, Photo, SectionHead, SourceLine, T, Tag, WeatherIcon, type Extra } from "./formatKit";
import type { TemplateProps } from "./shared";

/**
 * G · TABLERO DE SERVICIO Y RESUMEN (still 4:5 o 9:16). Una pieza por
 * `content.extra.kind`:
 * - digest-cover / digest-item / digest-close: carrusel "Lo que tenés que saber hoy" (8 h).
 * - weather: clima y alertas del SMN.  - dollar: cotizaciones.
 * - holidays: proximos feriados.       - services: agua, luz y pasos fronterizos.
 * - quake: sismo en Salta (INPRES), placa fija sin IA.
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

type Day = { label: string; min: number; max: number; desc: string; rain: number };

/** Barra de temperatura: tramo min-max del dia sobre la escala de la semana, con marca opcional de "ahora". */
const TempBar: React.FC<{ u: number; lo: number; hi: number; min: number; max: number; now?: number; h: number }> = ({ u, lo, hi, min, max, now, h }) => {
  const span = Math.max(1, hi - lo);
  const pct = (v: number) => `${Math.min(100, Math.max(0, ((v - lo) / span) * 100))}%`;
  return (
    <div style={{ position: "relative", height: h, background: "rgba(255,255,255,0.12)", borderRadius: h }}>
      <div style={{ position: "absolute", top: 0, bottom: 0, left: pct(min), right: `calc(100% - ${pct(max)})`, borderRadius: h, background: "linear-gradient(90deg, #6CC9FF 0%, #FFB700 100%)" }} />
      {now !== undefined ? (
        <div style={{ position: "absolute", top: -6 * u, bottom: -6 * u, left: pct(now), width: 8 * u, marginLeft: -4 * u, background: brand.colors.white, boxShadow: "0 0 0 4px rgba(30,13,51,0.9)" }} />
      ) : null}
    </div>
  );
};

const Weather: React.FC<{ x: Extra; box: Box }> = ({ x, box }) => {
  const { u, m } = box;
  // 2026-10-23: sin "proximos dias"; el hoy ocupa toda la placa.
  const k = box.story ? 1 : 0.78;
  const now = x.now as { temp: number; desc: string; humidity: number; wind: string; time: string };
  const days = (x.days as Day[]) ?? [];
  const today = days[0];
  const level = Math.min(4, Math.max(1, Number(x.alertLevel ?? 1)));
  const a = ALERT[level];
  const tip = x.tip ? String(x.tip) : "";
  const chip = (text: string) => (
    <span style={{ ...roleStyle(textRoles.meta, Math.round(30 * u * k)), padding: `${16 * u * k}px ${22 * u * k}px`, background: "rgba(255,255,255,0.1)", color: "rgba(255,255,255,0.92)" }}>{upper(text)}</span>
  );
  return (
    <BrandFrame corners={0.08}>
      <Logo box={box} />
      <div style={{ position: "absolute", left: m, right: m, top: box.top, bottom: box.H - box.bottom + 80 * u, display: "flex", flexDirection: "column", justifyContent: "space-between", gap: 30 * u * k }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 20 * u }}>
          <SectionHead label="El tiempo en Salta" size={Math.round(26 * u)} color="#6CC9FF" />
          <span style={{ ...roleStyle(textRoles.meta, Math.round(26 * u)), color: "rgba(255,255,255,0.8)" }}>{upper(String(x.dateLabel ?? ""))}</span>
        </div>
        {today ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 * u * k }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 20 * u }}>
              <div style={{ display: "flex", flexDirection: "column" }}>
                <span style={{ ...roleStyle(textRoles.kicker, Math.round(34 * u * k)), color: brand.colors.accent }}>HOY · MÁXIMA</span>
                <span style={{ ...roleStyle(textRoles.dataNumber, Math.round(340 * u * k)), color: brand.colors.white, lineHeight: 1 }}>{fmtNum(today.max)}°</span>
              </div>
              <WeatherIcon desc={today.desc} size={Math.round(330 * u * k)} />
            </div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 26 * u }}>
              <span style={{ ...roleStyle(textRoles.kicker, Math.round(34 * u * k)), color: "#6CC9FF" }}>MÍNIMA</span>
              <span style={{ ...roleStyle(textRoles.dataNumber, Math.round(130 * u * k)), color: "#6CC9FF" }}>{fmtNum(today.min)}°</span>
            </div>
            <T role={textRoles.breakingHeadline} size={Math.round(84 * u * k)}>
              {today.desc}
            </T>
          </div>
        ) : null}
        {today ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 * u }}>
            <TempBar u={u} lo={today.min - 1} hi={today.max + 1} min={today.min} max={today.max} now={now.temp} h={Math.round(44 * u * k)} />
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ ...roleStyle(textRoles.meta, Math.round(28 * u * k)), color: "#6CC9FF" }}>MÍN {fmtNum(today.min)}°</span>
              <span style={{ ...roleStyle(textRoles.meta, Math.round(28 * u * k)), color: brand.colors.white }}>{upper(`Ahora ${fmtNum(now.temp, 0)}°${now.time ? ` · ${now.time} h` : ""}`)}</span>
              <span style={{ ...roleStyle(textRoles.meta, Math.round(28 * u * k)), color: brand.colors.accent }}>MÁX {fmtNum(today.max)}°</span>
            </div>
          </div>
        ) : null}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 14 * u }}>
          {today ? chip(`💧 Lluvia ${today.rain}%`) : null}
          {chip(`Humedad ${fmtNum(now.humidity)}%`)}
          {chip(`Viento ${now.wind}`)}
        </div>
        {level >= 2 ? (
          <div style={{ padding: `${30 * u}px ${30 * u}px`, background: a.color, display: "flex", flexDirection: "column", gap: 8 * u }}>
            <span style={{ ...roleStyle(textRoles.kicker, Math.round(44 * u * k)), color: a.text }}>⚠ {upper(a.label)} PARA HOY</span>
            <span style={{ ...roleStyle(textRoles.meta, Math.round(26 * u * k)), color: a.text }}>SEGUÍ LOS AVISOS OFICIALES DEL SMN</span>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 18 * u }}>
            <div style={{ display: "flex", alignItems: "center", padding: `${14 * u}px ${20 * u}px`, background: a.color, alignSelf: "flex-start" }}>
              <span style={{ ...roleStyle(textRoles.kicker, Math.round(26 * u * k)), color: a.text }}>{upper(a.label)}</span>
            </div>
            {tip ? (
              <T role={textRoles.deckStrong} size={Math.round(44 * u * k)} color="rgba(255,255,255,0.92)">
                {tip}
              </T>
            ) : null}
          </div>
        )}
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

const Quake: React.FC<{ x: Extra; box: Box }> = ({ x, box }) => {
  const { u, m } = box;
  const magnitude = Number(x.magnitude ?? 0);
  const near = Number(x.nearKm ?? 0) < 15 ? String(x.near ?? "") : `a ${x.nearKm} km de ${x.near}`;
  const facts: [string, string][] = [
    ["Hora", String(x.timeLabel ?? "")],
    ["Profundidad", `${x.depthKm} km`],
    ["Desde la Capital", `${x.capitalKm} km`],
  ];
  return (
    <BrandFrame corners={0.1}>
      <Logo box={box} />
      <div style={{ position: "absolute", left: m, right: m, top: box.top, bottom: box.H - box.bottom + 100 * u, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
        <SectionHead label={x.felt ? "Sismo sentido" : "Sismo"} date={String(x.dateLabel ?? "")} size={Math.round(26 * u)} color={brand.colors.signal} />
        <div style={{ display: "flex", alignItems: "baseline", gap: 22 * u }}>
          <span style={{ ...roleStyle(textRoles.dataNumber, Math.round(300 * u)), color: brand.colors.accent }}>{fmtNum(magnitude, 1)}</span>
          <span style={{ ...roleStyle(textRoles.kicker, Math.round(34 * u)), color: "rgba(255,255,255,0.8)" }}>MAGNITUD</span>
        </div>
        <T role={textRoles.breakingHeadline} size={Math.round(84 * u)}>
          Tembló en Salta: epicentro {near}
        </T>
        <div style={{ display: "flex", flexDirection: "column", gap: 14 * u }}>
          {facts.map(([label, value]) => (
            <div key={label} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: `${24 * u}px ${24 * u}px`, background: "rgba(255,255,255,0.08)" }}>
              <span style={{ ...roleStyle(textRoles.kicker, Math.round(26 * u)), color: brand.colors.accent }}>{upper(label)}</span>
              <span style={{ ...roleStyle(textRoles.dataNumber, Math.round(54 * u)), color: brand.colors.white }}>{value}</span>
            </div>
          ))}
        </div>
      </div>
      <Footer box={box} source={x.state === "preliminar" ? "Fuente: INPRES · dato preliminar" : "Fuente: INPRES"} />
    </BrandFrame>
  );
};

// ---------- Fondo alusivo (propuesta 23/10: ilustracion propia o foto con licencia libre) ----------

type Theme = "luz" | "agua" | "paso" | "dolar" | "sueldo" | "anses";
type Bg = { mode?: "none" | "art" | "photo"; theme?: Theme; photo?: string; credit?: string };

const ART: Record<Theme, React.ReactNode> = {
  luz: (
    <g>
      <path d="M50 6 L30 98 M50 6 L70 98 M36 70 H64 M40 48 H60 M45 26 H55 M14 26 H86 M20 48 H80 M40 48 L45 26 M60 48 L55 26 M33 82 L64 70 M36 70 L67 82" />
      <path d="M14 26 Q -6 34 -20 30 M86 26 Q 106 34 120 30 M20 48 Q 0 58 -20 54 M80 48 Q 100 58 120 54" />
      <path d="M84 70 l-8 13 h7 l-5 12 13-16 h-7 l5-9 Z" fill="currentColor" />
    </g>
  ),
  agua: (
    <g>
      <path d="M50 8 C 50 8 24 44 24 62 a26 26 0 0 0 52 0 C 76 44 50 8 50 8 Z" />
      <path d="M38 64 a12 12 0 0 0 10 12" />
      <path d="M-10 92 q 10 -6 20 0 t 20 0 t 20 0 t 20 0 t 20 0 t 20 0 M-10 100 q 10 -6 20 0 t 20 0 t 20 0 t 20 0 t 20 0 t 20 0" />
      <path d="M84 18 C 84 18 76 30 76 35 a8 8 0 0 0 16 0 C 92 30 84 18 84 18 Z" />
    </g>
  ),
  paso: (
    <g>
      <path d="M-5 70 L18 38 L30 52 L52 16 L72 46 L84 34 L105 64" />
      <path d="M46 23 L52 16 L58 25 M80 39 L84 34 L89 41" />
      <path d="M38 100 L49 70 M66 100 L55 70 M52 98 V92 M52 86 V81 M52 77 V73" />
      <path d="M-5 70 H105" />
    </g>
  ),
  dolar: (
    <g>
      <path d="M62 24 C 58 18 52 16 46 16 C 36 16 30 22 30 30 C 30 46 66 40 66 58 C 66 68 58 74 48 74 C 40 74 34 70 30 64 M48 8 V82" />
      <circle cx="82" cy="78" r="14" />
      <circle cx="82" cy="78" r="9" />
      <circle cx="14" cy="86" r="10" />
    </g>
  ),
  sueldo: (
    <g>
      <rect x="18" y="20" width="64" height="62" rx="4" />
      <path d="M18 36 H82 M32 12 V28 M68 12 V28 M30 48 h8 M46 48 h8 M62 48 h8 M30 60 h8 M46 60 h8 M30 72 h8" />
      <circle cx="66" cy="66" r="9" fill="currentColor" />
    </g>
  ),
  anses: (
    <g>
      <rect x="10" y="26" width="80" height="50" rx="5" />
      <path d="M10 40 H90 M20 62 h22 M20 68 h14" />
      <circle cx="72" cy="62" r="7" />
    </g>
  ),
};

/** Capa de fondo: ilustracion de linea (sin licencias) o foto en duotono violeta. */
const BgLayer: React.FC<{ bg?: Bg; box: Box }> = ({ bg, box }) => {
  if (!bg || !bg.mode || bg.mode === "none" || !bg.theme) return null;
  const { W, H, u } = box;
  if (bg.mode === "photo" && bg.photo) {
    return (
      <AbsoluteFill>
        <Photo src={bg.photo} style={{ filter: "grayscale(1) contrast(1.15) brightness(0.9)" }} focusY={0.5} />
        <AbsoluteFill style={{ background: brand.field, opacity: 0.84, mixBlendMode: "multiply" }} />
        <AbsoluteFill style={{ background: "linear-gradient(to bottom, rgba(30,13,51,0.55) 0%, rgba(30,13,51,0.25) 35%, rgba(30,13,51,0.85) 100%)" }} />
        {bg.credit ? (
          <span style={{ ...roleStyle(textRoles.meta, Math.round(13 * u)), position: "absolute", right: 14 * u, top: H * 0.45, transformOrigin: "right top", rotate: "-90deg", color: "rgba(255,255,255,0.55)" }}>{bg.credit}</span>
        ) : null}
      </AbsoluteFill>
    );
  }
  const size = W * 0.95;
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <svg
        viewBox="0 0 100 100"
        width={size}
        height={size}
        style={{ position: "absolute", right: -W * 0.18, top: H * (box.story ? 0.3 : 0.24), color: brand.colors.accent, opacity: 0.13 }}
        fill="none"
        stroke="#FFFFFF"
        strokeWidth={1.1}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {ART[bg.theme]}
      </svg>
    </AbsoluteFill>
  );
};

/** BrandFrame con la capa de fondo debajo de las esquinas ambar. */
const ThemedFrame: React.FC<{ x: Extra; box: Box; corners?: number; children: React.ReactNode }> = ({ x, box, corners = 0.08, children }) => (
  <BrandFrame corners={0}>
    <BgLayer bg={x.bg as Bg | undefined} box={box} />
    <AbsoluteFill style={{ background: brand.colors.accent, clipPath: slashCorner(1, box.W, box.H, "top-left", corners) }} />
    <AbsoluteFill style={{ background: brand.colors.accent, clipPath: slashCorner(1, box.W, box.H, "bottom-right", corners * 0.8) }} />
    {children}
  </BrandFrame>
);

const StatusChip: React.FC<{ label: string; color: string; textColor?: string; size: number }> = ({ label, color, textColor = brand.colors.ink, size }) => (
  <span style={{ ...roleStyle(textRoles.kicker, size), padding: `${size * 0.35}px ${size * 0.6}px`, background: color, color: textColor, alignSelf: "flex-start" }}>{upper(label)}</span>
);

/** Barra horaria de 6 a 22 h con el tramo afectado; sin hora de fin, el tramo se desvanece hasta el final. */
const HourBar: React.FC<{ u: number; from?: number; to?: number | null; h: number; color: string; now?: number }> = ({ u, from, to, h, color, now }) => {
  const lo = 6;
  const hi = 22;
  const pct = (v: number) => Math.min(100, Math.max(0, ((v - lo) / (hi - lo)) * 100));
  const ticks = [6, 10, 14, 18, 22];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 * u }}>
      <div style={{ position: "relative", height: h, background: "rgba(255,255,255,0.12)" }}>
        {from !== undefined ? (
          <div
            style={{
              position: "absolute",
              top: 0,
              bottom: 0,
              left: `${pct(from)}%`,
              width: `${(to ? pct(to) : 100) - pct(from)}%`,
              background: to ? color : `linear-gradient(90deg, ${color} 0%, ${color} 40%, rgba(255,255,255,0) 100%)`,
            }}
          />
        ) : null}
        {now !== undefined ? <div style={{ position: "absolute", top: -8 * u, bottom: -8 * u, left: `${pct(now)}%`, width: 8 * u, marginLeft: -4 * u, background: brand.colors.signal }} /> : null}
      </div>
      <div style={{ position: "relative", height: 26 * u }}>
        {ticks.map((t) => (
          <span key={t} style={{ ...roleStyle(textRoles.meta, Math.round(20 * u)), color: "rgba(255,255,255,0.6)", position: "absolute", left: `${pct(t)}%`, transform: t === hi ? "translateX(-100%)" : t === lo ? "none" : "translateX(-50%)" }}>
            {String(t).padStart(2, "0")}
          </span>
        ))}
      </div>
    </div>
  );
};

const CUT_STATUS: Record<string, { label: string; color: string; text: string }> = {
  hoy: { label: "Hoy", color: brand.colors.signal, text: brand.colors.white },
  ahora: { label: "En curso", color: brand.colors.signal, text: brand.colors.white },
  manana: { label: "Mañana", color: brand.colors.accent, text: brand.colors.ink },
  cancelado: { label: "Cancelado", color: "#2ED394", text: brand.colors.ink },
};

/** Corte de luz (EDESA) o de agua (Aguas del Norte): zona, franja horaria y barrios. */
const Cut: React.FC<{ x: Extra; box: Box }> = ({ x, box }) => {
  const { u, m, story } = box;
  const water = x.service === "agua";
  const tint = water ? "#6CC9FF" : brand.colors.accent;
  const status = CUT_STATUS[String(x.status ?? "hoy")] ?? { label: String(x.statusLabel ?? x.status), color: brand.colors.white, text: brand.colors.ink };
  const cancelled = x.status === "cancelado";
  const start = x.start ? String(x.start) : "";
  const end = x.end ? String(x.end) : "";
  const hour = (t: string) => (t ? Number(t.slice(0, 2)) + Number(t.slice(3, 5)) / 60 : undefined);
  const big = Math.round((story ? 210 : 170) * u);
  return (
    <ThemedFrame x={x} box={box}>
      <Logo box={box} />
      <div style={{ position: "absolute", left: m, right: m, top: box.top, bottom: box.H - box.bottom + 90 * u, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 * u }}>
          <Tag label={water ? "Corte de agua" : "Corte de luz"} color={tint} size={Math.round(28 * u)} />
          <StatusChip label={status.label} color={status.color} textColor={status.text} size={Math.round(24 * u)} />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 * u }}>
          <T role={textRoles.breakingHeadline} size={Math.round((story ? 150 : 128) * u)} lines={2}>
            {String(x.place ?? "")}
          </T>
          <span style={{ ...roleStyle(textRoles.kicker, Math.round(30 * u)), color: "rgba(255,255,255,0.82)" }}>{upper(String(x.sub ?? ""))}</span>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 22 * u }}>
          {cancelled ? (
            <span style={{ ...roleStyle(textRoles.dataNumber, big), color: "rgba(255,255,255,0.45)", textDecoration: "line-through", textDecorationThickness: 8 * u }}>{start}</span>
          ) : end ? (
            <div style={{ display: "flex", flexDirection: story ? "column" : "row", alignItems: story ? "flex-start" : "baseline", gap: story ? 0 : 26 * u }}>
              <span style={{ ...roleStyle(textRoles.dataNumber, big), color: tint }}>{start}</span>
              {story ? null : <span style={{ ...roleStyle(textRoles.dataNumber, Math.round(90 * u)), color: "rgba(255,255,255,0.6)" }}>→</span>}
              <span style={{ ...roleStyle(textRoles.dataNumber, big), color: brand.colors.white }}>{end}</span>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 * u }}>
              <span style={{ ...roleStyle(textRoles.kicker, Math.round(30 * u)), color: tint }}>{upper(start ? `Desde las ${start}` : String(x.since ?? "Desde hoy"))}</span>
              <T role={textRoles.breakingHeadline} size={Math.round((story ? 120 : 104) * u)}>
                Hasta normalizar
              </T>
            </div>
          )}
          {cancelled ? null : <HourBar u={u} from={hour(start) ?? 6} to={end ? hour(end) : null} h={Math.round(26 * u)} color={tint} />}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 14 * u }}>
          <T role={textRoles.deckStrong} size={Math.round((story ? 42 : 36) * u)} lines={story ? 5 : 3}>
            {String(x.detail ?? "")}
          </T>
          {x.reason ? <span style={{ ...roleStyle(textRoles.meta, Math.round(22 * u)), whiteSpace: "normal", color: "rgba(255,255,255,0.7)" }}>{upper(`Motivo: ${x.reason}`)}</span> : null}
        </div>
      </div>
      <Footer box={box} source={String(x.source ?? "")} />
    </ThemedFrame>
  );
};

/** Paso fronterizo cerrado dentro de su horario habitual (o reabierto). */
const PassClosed: React.FC<{ x: Extra; box: Box }> = ({ x, box }) => {
  const { u, m, story } = box;
  const open = x.state === "ABIERTO";
  const hours = String(x.hours ?? "");
  const hm = /(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})/.exec(hours);
  const now = x.nowH !== undefined ? Number(x.nowH) : undefined;
  return (
    <ThemedFrame x={x} box={box}>
      <Logo box={box} />
      <div style={{ position: "absolute", left: m, right: m, top: box.top, bottom: box.H - box.bottom + 90 * u, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
        <SectionHead label="Paso internacional" size={Math.round(26 * u)} color={open ? "#2ED394" : brand.colors.signal} />
        <div style={{ display: "flex", flexDirection: "column", gap: 12 * u }}>
          <T role={textRoles.breakingHeadline} size={Math.round((story ? 160 : 140) * u)} lines={2}>
            {String(x.name ?? "")}
          </T>
          <span style={{ ...roleStyle(textRoles.kicker, Math.round(30 * u)), color: "rgba(255,255,255,0.82)" }}>{upper(String(x.route ?? ""))}</span>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 * u, padding: `${26 * u}px ${30 * u}px`, background: open ? "#2ED394" : brand.colors.signal }}>
          <span style={{ ...roleStyle(textRoles.dataNumber, Math.round((story ? 130 : 110) * u)), color: open ? brand.colors.ink : brand.colors.white }}>{open ? "HABILITADO" : "CERRADO"}</span>
          <span style={{ ...roleStyle(textRoles.kicker, Math.round(26 * u)), color: open ? brand.colors.ink : brand.colors.white }}>{upper(String(x.sinceLabel ?? ""))}</span>
        </div>
        {hm ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 14 * u }}>
            <span style={{ ...roleStyle(textRoles.kicker, Math.round(24 * u)), color: brand.colors.accent }}>{upper(`Horario habitual ${hm[1]}:${hm[2]} a ${hm[3]}:${hm[4]}`)}</span>
            <HourBar u={u} from={Number(hm[1]) + Number(hm[2]) / 60} to={Number(hm[3]) + Number(hm[4]) / 60} h={Math.round(22 * u)} color="rgba(46,211,148,0.75)" now={now} />
          </div>
        ) : null}
        <div style={{ display: "flex", flexDirection: "column", gap: 10 * u, padding: `${22 * u}px ${24 * u}px`, background: "rgba(255,255,255,0.08)", borderLeft: `${6 * u}px solid ${brand.colors.accent}` }}>
          <span style={{ ...roleStyle(textRoles.meta, Math.round(20 * u)), color: brand.colors.accent }}>{x.note ? "LO QUE INFORMA EL ESTADO" : "ANTES DE VIAJAR"}</span>
          <T role={textRoles.deckStrong} size={Math.round(34 * u)}>
            {String(x.note || "Consultá el estado del paso antes de salir: puede cambiar durante el día.")}
          </T>
        </div>
      </div>
      <Footer box={box} source={String(x.source ?? "")} />
    </ThemedFrame>
  );
};

/** Dolar, version tablero: oficial y blue en grande, brecha y el resto en tarjetas. */
const Dollar2: React.FC<{ x: Extra; box: Box }> = ({ x, box }) => {
  const { u, m, story } = box;
  const quotes = (x.quotes as { id: string; name: string; buy?: number; sell: number; prev?: number }[]) ?? [];
  const main = quotes.filter((q) => q.id === "oficial" || q.id === "blue");
  const rest = quotes.filter((q) => q.id !== "oficial" && q.id !== "blue");
  const money = (n: number) => `$${fmtNum(n, n % 1 ? 1 : 0)}`;
  const delta = (q: { sell: number; prev?: number }) => {
    if (!q.prev) return null;
    const d = q.sell - q.prev;
    const color = d > 0 ? "#FF6A3D" : d < 0 ? "#2ED394" : "rgba(255,255,255,0.7)";
    return <span style={{ ...roleStyle(textRoles.meta, Math.round(22 * u)), color }}>{d > 0 ? "▲" : d < 0 ? "▼" : "="} {d ? `$${fmtNum(Math.abs(d))}` : "IGUAL"} VS AYER</span>;
  };
  const gap = x.gap !== undefined ? Number(x.gap) : undefined;
  return (
    <ThemedFrame x={x} box={box}>
      <Logo box={box} />
      <div style={{ position: "absolute", left: m, right: m, top: box.top, bottom: box.H - box.bottom + 90 * u, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
        <SectionHead label="Dólar hoy" date={String(x.dateLabel ?? "")} size={Math.round(26 * u)} color="#2ED394" />
        <T role={textRoles.breakingHeadline} size={Math.round((story ? 104 : 92) * u)}>
          ¿A cuánto está el <span style={{ color: "#2ED394" }}>dólar</span>?
        </T>
        <div style={{ display: "flex", flexDirection: story ? "column" : "row", gap: 18 * u }}>
          {main.map((q) => (
            <div key={q.id} style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 8 * u, padding: `${26 * u}px ${28 * u}px`, background: "rgba(255,255,255,0.09)", borderTop: `${8 * u}px solid ${q.id === "blue" ? "#6CC9FF" : "#2ED394"}` }}>
              <span style={{ ...roleStyle(textRoles.kicker, Math.round(30 * u)), color: q.id === "blue" ? "#6CC9FF" : "#2ED394" }}>{upper(`Dólar ${q.name}`)}</span>
              <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 16 * u }}>
                <span style={{ ...roleStyle(textRoles.dataNumber, Math.round((story ? 150 : 118) * u)), color: brand.colors.white }}>{money(q.sell)}</span>
                {story ? delta(q) : null}
              </div>
              <span style={{ ...roleStyle(textRoles.meta, Math.round(22 * u)), color: "rgba(255,255,255,0.72)" }}>{q.buy ? `COMPRA ${money(q.buy)}` : "VENTA"}</span>
              {story ? null : delta(q)}
            </div>
          ))}
        </div>
        {gap !== undefined ? (
          <div style={{ display: "flex", alignItems: "center", gap: 20 * u }}>
            <span style={{ ...roleStyle(textRoles.kicker, Math.round(24 * u)), color: brand.colors.accent, flex: "none" }}>BRECHA BLUE / OFICIAL</span>
            <div style={{ flex: 1, height: 3 * u, background: "rgba(255,255,255,0.2)" }} />
            <span style={{ ...roleStyle(textRoles.dataNumber, Math.round(54 * u)), color: brand.colors.white }}>{fmtNum(gap, 1)}%</span>
          </div>
        ) : null}
        <div style={{ display: "grid", gridTemplateColumns: `repeat(${rest.length}, 1fr)`, gap: 14 * u }}>
          {rest.map((q) => (
            <div key={q.id} style={{ display: "flex", flexDirection: "column", gap: 6 * u, padding: `${20 * u}px ${20 * u}px`, background: "rgba(255,255,255,0.07)" }}>
              <span style={{ ...roleStyle(textRoles.kicker, Math.round(22 * u)), color: brand.colors.accent }}>{upper(q.name)}</span>
              <span style={{ ...roleStyle(textRoles.dataNumber, Math.round(58 * u)), color: brand.colors.white }}>{money(q.sell)}</span>
            </div>
          ))}
        </div>
        <span style={{ ...roleStyle(textRoles.meta, Math.round(19 * u)), whiteSpace: "normal", color: "rgba(255,255,255,0.65)" }}>{upper(`Valores de venta · ${x.updated ?? ""}`)}</span>
      </div>
      <Footer box={box} source="Fuente: DolarApi / BCRA" />
    </ThemedFrame>
  );
};

/** Sueldos de la Administracion Publica de Salta. A: fecha gigante; B: calendario del mes. */
const Payday: React.FC<{ x: Extra; box: Box }> = ({ x, box }) => {
  const { u, m, story } = box;
  const sectors = (x.sectors as string[]) ?? [];
  const day = Number(x.day ?? 1);
  const monthDays = Number(x.monthDays ?? 31);
  const firstWeekday = Number(x.firstWeekday ?? 0); // 0 = lunes
  const today = Number(x.today ?? 0);
  const variant = String(x.variant ?? "A");
  // 2026-10-23: solo las semanas que van de hoy al dia de cobro, para que los numeros se lean en el celular.
  const cellOf = (n: number) => n + firstWeekday - 1;
  const toRow = Math.floor(cellOf(day) / 7);
  const fromRow = Math.max(toRow - 1, Math.floor(cellOf(today > 0 ? Math.min(today, day) : 1) / 7));
  const rows = Array.from({ length: toRow - fromRow + 1 }, (_, r) => fromRow + r);
  const cellH = Math.round((story ? 160 : 112) * u);
  const chips = (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 14 * u }}>
      {sectors.map((s) => (
        <span key={s} style={{ ...roleStyle(textRoles.kicker, Math.round((story ? 34 : 28) * u)), padding: `${14 * u}px ${20 * u}px`, background: "rgba(255,255,255,0.12)", color: brand.colors.white }}>
          ✓ {upper(s)}
        </span>
      ))}
    </div>
  );
  const extraLine = x.extra ? (
    <div style={{ padding: `${22 * u}px ${26 * u}px`, background: "rgba(255,183,0,0.14)", borderLeft: `${8 * u}px solid ${brand.colors.accent}` }}>
      <T role={textRoles.deckStrong} size={Math.round((story ? 44 : 36) * u)}>
        {String(x.extra)}
      </T>
    </div>
  ) : null;
  return (
    <ThemedFrame x={x} box={box}>
      <Logo box={box} />
      <div style={{ position: "absolute", left: m, right: m, top: box.top, bottom: box.H - box.bottom + 90 * u, display: "flex", flexDirection: "column", justifyContent: "space-between", gap: 24 * u }}>
        <SectionHead label="Sueldos estatales" size={Math.round(28 * u)} />
        {variant === "A" ? (
          <div style={{ display: "flex", flexDirection: "column" }}>
            <span style={{ ...roleStyle(textRoles.kicker, Math.round(34 * u)), color: "rgba(255,255,255,0.85)" }}>LOS ESTATALES COBRAN EL</span>
            <div style={{ display: "flex", alignItems: "flex-end", gap: 26 * u }}>
              <span style={{ ...roleStyle(textRoles.dataNumber, Math.round((story ? 400 : 330) * u)), color: brand.colors.accent, lineHeight: 0.9 }}>{day}</span>
              <div style={{ display: "flex", flexDirection: "column", paddingBottom: 30 * u }}>
                <span style={{ ...roleStyle(textRoles.breakingHeadline, Math.round(78 * u)), color: brand.colors.white }}>{upper(String(x.weekday ?? ""))}</span>
                <span style={{ ...roleStyle(textRoles.kicker, Math.round(40 * u)), color: "rgba(255,255,255,0.85)" }}>{upper(`de ${x.month ?? ""}`)}</span>
              </div>
            </div>
          </div>
        ) : (
          <>
            <T role={textRoles.breakingHeadline} size={Math.round((story ? 124 : 100) * u)}>
              Los estatales cobran el <span style={{ color: brand.colors.accent }}>{`${String(x.weekday ?? "").toLowerCase()} ${day}`}</span>
            </T>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 * u }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                <span style={{ ...roleStyle(textRoles.kicker, Math.round(30 * u)), color: brand.colors.accent }}>{upper(String(x.month ?? ""))}</span>
                {x.daysLeft !== undefined ? <span style={{ ...roleStyle(textRoles.kicker, Math.round(30 * u)), color: brand.colors.white }}>{`FALTAN ${x.daysLeft} DÍAS`}</span> : null}
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 10 * u }}>
                {["L", "M", "M", "J", "V", "S", "D"].map((d, i) => (
                  <span key={i} style={{ ...roleStyle(textRoles.kicker, Math.round(26 * u)), color: "rgba(255,255,255,0.65)", textAlign: "center" }}>{d}</span>
                ))}
                {rows.flatMap((r) =>
                  Array.from({ length: 7 }, (_, c) => {
                    const n = r * 7 + c - firstWeekday + 1;
                    if (n < 1 || n > monthDays) return <span key={`${r}-${c}`} />;
                    const pay = n === day;
                    const past = today > 0 && n < today;
                    return (
                      <div key={n} style={{ height: cellH, display: "flex", alignItems: "center", justifyContent: "center", background: pay ? brand.colors.accent : past ? "rgba(255,255,255,0.03)" : "rgba(255,255,255,0.1)", outline: n === today ? `${5 * u}px solid #FFFFFF` : "none", outlineOffset: -5 * u }}>
                        <span style={{ ...roleStyle(textRoles.dataNumber, Math.round(cellH * (pay ? 0.62 : 0.46))), color: pay ? brand.colors.ink : past ? "rgba(255,255,255,0.3)" : brand.colors.white }}>{n}</span>
                      </div>
                    );
                  }),
                )}
              </div>
              <span style={{ ...roleStyle(textRoles.meta, Math.round(24 * u)), color: "rgba(255,255,255,0.75)" }}>□ HOY · ■ DÍA DE COBRO</span>
            </div>
          </>
        )}
        <div style={{ display: "flex", flexDirection: "column", gap: 20 * u }}>
          {chips}
          {extraLine}
        </div>
      </div>
      <Footer box={box} source={String(x.source ?? "Fuente: Gobierno de Salta")} />
    </ThemedFrame>
  );
};

/** ANSES: quienes cobran hoy, desde el calendario oficial (resolucion en el Boletin Oficial). */
const AnsesToday: React.FC<{ x: Extra; box: Box }> = ({ x, box }) => {
  const { u, m, story } = box;
  const groups = (x.groups as { who: string; digits: string[] }[]) ?? [];
  const upcoming = ((x.upcoming as { label: string; items: { label: string; digits: string[] }[] }[]) ?? []).slice(0, story ? 5 : 3);
  const digitBox = (d: string, size: number, bgc: string, fg: string) => (
    <div key={d} style={{ width: size * 0.82, height: size, display: "flex", alignItems: "center", justifyContent: "center", background: bgc, flex: "none" }}>
      <span style={{ ...roleStyle(textRoles.dataNumber, Math.round(size * 0.82)), color: fg }}>{d}</span>
    </div>
  );
  const big = Math.round((story ? (groups.length > 1 ? 170 : 220) : groups.length > 1 ? 130 : 170) * u);
  return (
    <ThemedFrame x={x} box={box}>
      <Logo box={box} />
      <div style={{ position: "absolute", left: m, right: m, top: box.top, bottom: box.H - box.bottom + 90 * u, display: "flex", flexDirection: "column", justifyContent: "space-between", gap: 24 * u }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 18 * u }}>
          <SectionHead label="ANSES · Quién cobra hoy" size={Math.round(26 * u)} color="#6CC9FF" />
          <span style={{ ...roleStyle(textRoles.meta, Math.round(24 * u)), color: "rgba(255,255,255,0.8)" }}>{upper(String(x.dateLabel ?? ""))}</span>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 26 * u }}>
          <span style={{ ...roleStyle(textRoles.kicker, Math.round(30 * u)), color: brand.colors.accent }}>HOY COBRAN · DNI TERMINADOS EN</span>
          {groups.map((g) => (
            <div key={g.who} style={{ display: "flex", alignItems: "center", gap: 28 * u }}>
              <div style={{ display: "flex", gap: 14 * u }}>{g.digits.map((d) => digitBox(d, big, brand.colors.accent, brand.colors.ink))}</div>
              <T role={textRoles.postHeadline} size={Math.round((story ? 50 : 42) * u)} style={{ flex: 1, minWidth: 0 }}>
                {g.who}
              </T>
            </div>
          ))}
        </div>
        {upcoming.length ? (
          <div style={{ display: "flex", flexDirection: "column" }}>
            <span style={{ ...roleStyle(textRoles.kicker, Math.round(24 * u)), color: "#6CC9FF", marginBottom: 8 * u }}>PRÓXIMOS PAGOS</span>
            {upcoming.map((day, i) => (
              <div key={day.label} style={{ display: "flex", alignItems: "center", gap: 22 * u, padding: `${(story ? 20 : 14) * u}px 0`, borderTop: i ? "1px solid rgba(255,255,255,0.14)" : "none" }}>
                <span style={{ ...roleStyle(textRoles.kicker, Math.round(28 * u)), color: brand.colors.white, width: 130 * u, flex: "none" }}>{upper(day.label)}</span>
                <div style={{ display: "flex", flexDirection: "column", gap: 10 * u, flex: 1, minWidth: 0 }}>
                  {day.items.map((it) => (
                    <div key={it.label} style={{ display: "flex", alignItems: "center", gap: 16 * u }}>
                      <div style={{ display: "flex", gap: 6 * u }}>{it.digits.map((d) => digitBox(d, Math.round(56 * u), "rgba(255,255,255,0.14)", brand.colors.white))}</div>
                      <span style={{ ...roleStyle(textRoles.deckStrong, Math.round(28 * u)), whiteSpace: "normal", color: "rgba(255,255,255,0.9)" }}>{it.label}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : null}
        <div style={{ padding: `${18 * u}px ${22 * u}px`, background: "rgba(255,255,255,0.08)", borderLeft: `${6 * u}px solid #6CC9FF` }}>
          <T role={textRoles.deck} size={Math.round(28 * u)} color="rgba(255,255,255,0.9)">
            {`Consultá tu fecha exacta en Mi ANSES con tu CUIL.${x.validUntil ? ` Las órdenes de pago del mes vencen el ${x.validUntil}.` : ""}`}
          </T>
        </div>
      </div>
      <Footer box={box} source={String(x.source ?? "Fuente: ANSES")} />
    </ThemedFrame>
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
    case "quake":
      return <Quake x={x} box={box} />;
    case "cut":
      return <Cut x={x} box={box} />;
    case "pass":
      return <PassClosed x={x} box={box} />;
    case "dollar2":
      return <Dollar2 x={x} box={box} />;
    case "payday":
      return <Payday x={x} box={box} />;
    case "anses":
      return <AnsesToday x={x} box={box} />;
    default:
      return <Unknown kind={x.kind} />;
  }
};

export const ServiceBoard: React.FC<TemplateProps> = ({ piece }) => (
  <FontGate>
    <BoardInner piece={piece} />
  </FontGate>
);

