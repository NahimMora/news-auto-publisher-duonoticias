"use client";

import React from "react";

/** Controles base del panel: densos, legibles, sin adornos. */

export const Section: React.FC<{ title: string; children: React.ReactNode; aside?: React.ReactNode }> = ({ title, children, aside }) => (
  <section className="border-b border-line px-5 py-5">
    <div className="mb-4 flex items-center justify-between">
      <h3 className="section-title">{title}</h3>
      {aside}
    </div>
    <div className="space-y-4">{children}</div>
  </section>
);

export const Field: React.FC<{ label: string; hint?: React.ReactNode; children: React.ReactNode }> = ({ label, hint, children }) => (
  <label className="block">
    <span className="label">{label}</span>
    {children}
    {hint ? <span className="mt-1.5 block text-[11.5px] leading-snug text-mute">{hint}</span> : null}
  </label>
);

export const TextInput: React.FC<{ value: string; onChange: (v: string) => void; placeholder?: string; type?: string }> = ({ value, onChange, placeholder, type = "text" }) => (
  <input className="field" type={type} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
);

export const TextArea: React.FC<{ value: string; onChange: (v: string) => void; rows?: number; placeholder?: string; large?: boolean }> = ({
  value,
  onChange,
  rows = 3,
  placeholder,
  large,
}) => (
  <textarea
    className={`field resize-y leading-snug ${large ? "text-[17px] font-[640]" : ""}`}
    rows={rows}
    value={value}
    placeholder={placeholder}
    onChange={(e) => onChange(e.target.value)}
  />
);

export function Segmented<T extends string>({ value, options, onChange }: { value: T; options: Array<{ value: T; label: string; title?: string }>; onChange: (v: T) => void }) {
  return (
    <div className="flex border border-line bg-ink p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          title={o.title}
          onClick={() => onChange(o.value)}
          className={`flex-1 px-2 py-1.5 text-[12.5px] transition-colors ${value === o.value ? "bg-amber font-[700] text-ink" : "text-soft hover:text-white"}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Select<T extends string>({ value, options, onChange }: { value: T; options: Array<{ value: T; label: string }>; onChange: (v: T) => void }) {
  return (
    <select className="field" value={value} onChange={(e) => onChange(e.target.value as T)}>
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export const Slider: React.FC<{ label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void; format?: (v: number) => string }> = ({
  label,
  value,
  min,
  max,
  step,
  onChange,
  format,
}) => (
  <div>
    <div className="mb-1 flex items-baseline justify-between">
      <span className="label !mb-0">{label}</span>
      <span className="font-mono text-[11.5px] text-white">{format ? format(value) : value}</span>
    </div>
    <input className="w-full" type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
  </div>
);

export const Toggle: React.FC<{ label: string; checked: boolean; onChange: (v: boolean) => void; hint?: string }> = ({ label, checked, onChange, hint }) => (
  <button type="button" onClick={() => onChange(!checked)} className="flex w-full items-center justify-between gap-3 text-left">
    <span>
      <span className="block text-[13.5px]">{label}</span>
      {hint ? <span className="block text-[11.5px] text-mute">{hint}</span> : null}
    </span>
    <span className={`relative h-5 w-9 shrink-0 transition-colors ${checked ? "bg-amber" : "bg-line-strong"}`}>
      <span className={`absolute top-0.5 h-4 w-4 bg-ink transition-all ${checked ? "left-[18px]" : "left-0.5"}`} />
    </span>
  </button>
);

export const SmallButton: React.FC<React.ButtonHTMLAttributes<HTMLButtonElement> & { tone?: "default" | "danger" | "accent" }> = ({ tone = "default", className, ...props }) => (
  <button
    type="button"
    {...props}
    className={`border px-2.5 py-1 text-[12px] transition-colors disabled:opacity-40 ${
      tone === "danger" ? "border-line text-mute hover:border-signal hover:text-signal" : tone === "accent" ? "border-amber bg-amber font-[700] text-ink hover:opacity-90" : "border-line-strong text-soft hover:border-amber hover:text-white"
    } ${className ?? ""}`}
  />
);
