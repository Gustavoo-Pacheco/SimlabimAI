"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import authors from "@shared/authors.json";

const UNKNOWN = authors.unknownSentinel;

export interface SongPickerOption {
  slug: string;
  title: string;
  author: string;
}

interface Props {
  options: SongPickerOption[];
  value: string;
  onChange: (slug: string) => void;
  newSongValue: string;
  loading?: boolean;
  placeholder?: string;
}

interface Rect {
  top: number;
  left: number;
  width: number;
}

export default function SongPicker({
  options,
  value,
  onChange,
  newSongValue,
  loading,
  placeholder = "Selecione uma música…",
}: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlight, setHighlight] = useState(0);
  const [rect, setRect] = useState<Rect | null>(null);
  const [mounted, setMounted] = useState(false);

  const buttonRef = useRef<HTMLButtonElement>(null);
  const popupRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => setMounted(true), []);

  const selected = useMemo(
    () => options.find((o) => o.slug === value),
    [options, value],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter(
      (o) =>
        o.title.toLowerCase().includes(q) ||
        o.author.toLowerCase().includes(q) ||
        o.slug.includes(q),
    );
  }, [options, query]);

  const totalRows = 1 + filtered.length;

  const updateRect = () => {
    const el = buttonRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    setRect({ top: r.bottom + 6, left: r.left, width: r.width });
  };

  useEffect(() => {
    if (!open) return;
    updateRect();
    const onClick = (e: MouseEvent) => {
      const t = e.target as Node;
      if (buttonRef.current?.contains(t)) return;
      if (popupRef.current?.contains(t)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
      else if (e.key === "ArrowDown") {
        e.preventDefault();
        setHighlight((h) => Math.min(totalRows - 1, h + 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setHighlight((h) => Math.max(0, h - 1));
      } else if (e.key === "Enter") {
        e.preventDefault();
        commit(highlight);
      }
    };
    const onScrollOrResize = () => updateRect();
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", onScrollOrResize);
    window.addEventListener("scroll", onScrollOrResize, true);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", onScrollOrResize);
      window.removeEventListener("scroll", onScrollOrResize, true);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, highlight, totalRows]);

  useEffect(() => {
    if (open) {
      setHighlight(0);
      setQuery("");
      setTimeout(() => searchRef.current?.focus(), 30);
    }
  }, [open]);

  const commit = (index: number) => {
    if (index === 0) onChange(newSongValue);
    else {
      const opt = filtered[index - 1];
      if (opt) onChange(opt.slug);
    }
    setOpen(false);
  };

  const label =
    value === newSongValue
      ? "+ Nova música"
      : selected
        ? selected.title +
          (selected.author !== UNKNOWN ? ` — ${selected.author}` : "")
        : placeholder;

  const popup =
    open && rect && mounted
      ? createPortal(
          <div
            ref={popupRef}
            role="listbox"
            className="overflow-hidden rounded-lg border border-[var(--color-rule)] bg-white"
            style={{
              position: "fixed",
              top: rect.top,
              left: rect.left,
              width: rect.width,
              zIndex: 9999,
              boxShadow:
                "0 10px 28px rgba(0,0,0,0.08), 0 2px 6px rgba(0,0,0,0.04)",
              animation:
                "reveal-in 180ms cubic-bezier(0.16, 1, 0.3, 1) forwards",
            }}
          >
            {options.length > 4 && (
              <div className="border-b border-[var(--color-rule)] px-3 py-2">
                <input
                  ref={searchRef}
                  type="text"
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value);
                    setHighlight(0);
                  }}
                  placeholder="Buscar música ou autor…"
                  className="w-full bg-transparent text-[14px] outline-none placeholder:text-[#b3b2af]"
                />
              </div>
            )}

            <ul className="max-h-72 overflow-y-auto py-1">
              <li
                role="option"
                aria-selected={highlight === 0}
                onMouseEnter={() => setHighlight(0)}
                onClick={() => commit(0)}
                className={`flex cursor-pointer items-center gap-2.5 px-3 py-2.5 text-[14px] transition-colors ${
                  highlight === 0
                    ? "bg-[var(--color-pastel-green-bg)] text-[color:var(--color-pastel-green-ink)]"
                    : "text-[color:var(--color-ink)]"
                }`}
              >
                <span
                  aria-hidden
                  className={`inline-flex h-5 w-5 items-center justify-center rounded-full border ${
                    highlight === 0
                      ? "border-[color:var(--color-pastel-green-ink)] text-[color:var(--color-pastel-green-ink)]"
                      : "border-[var(--color-rule)] text-[color:var(--color-ink-muted)]"
                  }`}
                >
                  <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                    <path
                      d="M5 1.5v7M1.5 5h7"
                      stroke="currentColor"
                      strokeWidth="1.4"
                      strokeLinecap="round"
                    />
                  </svg>
                </span>
                <span className="flex-1 font-medium">
                  Adicionar nova música
                </span>
              </li>

              {filtered.length > 0 && (
                <li
                  aria-hidden
                  className="my-1 h-px bg-[var(--color-rule)]"
                  role="presentation"
                />
              )}

              {filtered.map((o, i) => {
                const idx = i + 1;
                const active = highlight === idx;
                const isSelected = value === o.slug;
                return (
                  <li
                    key={o.slug}
                    role="option"
                    aria-selected={isSelected}
                    onMouseEnter={() => setHighlight(idx)}
                    onClick={() => commit(idx)}
                    className={`flex cursor-pointer items-center gap-2.5 px-3 py-2 text-[14px] transition-colors ${
                      active
                        ? "bg-[#f5f5f3] text-[color:var(--color-ink)]"
                        : "text-[color:var(--color-ink)]"
                    }`}
                  >
                    <span
                      aria-hidden
                      className={`inline-block h-1.5 w-1.5 rounded-full ${
                        isSelected
                          ? "bg-[color:var(--color-ink)]"
                          : "bg-[#dcdcd9]"
                      }`}
                    />
                    <span className="flex-1 truncate text-left">{o.title}</span>
                    {o.author !== UNKNOWN && (
                      <span className="shrink-0 text-[12px] text-[color:var(--color-ink-muted)]">
                        {o.author}
                      </span>
                    )}
                  </li>
                );
              })}

              {filtered.length === 0 && options.length > 0 && (
                <li className="px-3 py-3 text-center text-[13px] text-[color:var(--color-ink-muted)]">
                  Nenhuma música encontrada.
                </li>
              )}
            </ul>
          </div>,
          document.body,
        )
      : null;

  return (
    <div className="w-full">
      <button
        ref={buttonRef}
        type="button"
        onClick={() => !loading && setOpen((v) => !v)}
        disabled={loading}
        aria-haspopup="listbox"
        aria-expanded={open}
        className={`flex w-full items-center justify-between gap-2 rounded-md border border-[var(--color-rule)] bg-white px-3 py-2 text-[15px] text-[color:var(--color-ink)] outline-none transition-colors hover:border-[#cfcfcc] focus:border-[color:var(--color-ink)] disabled:opacity-60 ${
          !selected && value !== newSongValue ? "text-[#b3b2af]" : ""
        }`}
      >
        <span className="truncate text-left">
          {loading ? "Carregando…" : label}
        </span>
        <svg
          width="14"
          height="14"
          viewBox="0 0 12 12"
          fill="none"
          aria-hidden
          className={`shrink-0 text-[color:var(--color-ink-muted)] transition-transform duration-200 ${
            open ? "rotate-180" : ""
          }`}
        >
          <path
            d="M3 4.5l3 3 3-3"
            stroke="currentColor"
            strokeWidth="1.25"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
      {popup}
    </div>
  );
}
