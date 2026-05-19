"use client";

import { useEffect, useState } from "react";
import Recorder from "@/components/Recorder";
import SongPicker from "@/components/SongPicker";
import { isSlug, slugify, STYLES, type Style } from "@/lib/slugs";

interface SongOption {
  slug: string;
  title: string;
  author: string;
}

const STYLE_LABELS: Record<Style, string> = {
  cantar: "Cantar (com letra)",
  cantarolar: "Cantarolar (sem letra)",
  assobiar: "Assobiar",
};

const STYLE_HINTS: Record<Style, string> = {
  cantar: "Voz com palavras.",
  cantarolar: "Melodia sem palavras.",
  assobiar: "Apenas o assobio.",
};

const NEW_SONG = "__new__";

const inputClass =
  "w-full rounded-md border border-[var(--color-rule)] bg-white px-3 py-2 text-[15px] text-center text-[color:var(--color-ink)] outline-none transition-colors placeholder:text-[#b3b2af] focus:border-[color:var(--color-ink)]";

const labelClass = "text-[13px] text-[color:var(--color-ink-muted)]";

export default function HomePage() {
  const [songs, setSongs] = useState<SongOption[]>([]);
  const [songsLoaded, setSongsLoaded] = useState(false);

  const [contributor, setContributor] = useState("");
  const [songChoice, setSongChoice] = useState<string>("");
  const [newTitle, setNewTitle] = useState("");
  const [author, setAuthor] = useState("");
  const [style, setStyle] = useState<Style | "">("");
  const [wavBlob, setWavBlob] = useState<Blob | null>(null);

  const [submitting, setSubmitting] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const stored = localStorage.getItem("simlabim.contributor");
    if (stored) setContributor(stored);
  }, []);

  useEffect(() => {
    fetch("/api/songs")
      .then((r) => r.json() as Promise<{ songs?: SongOption[] }>)
      .then((data) => {
        setSongs(data.songs ?? []);
        setSongsLoaded(true);
      })
      .catch((err) => {
        console.error(err);
        setError("Falha ao carregar músicas");
        setSongsLoaded(true);
      });
  }, []);

  const isAddingNew = songChoice === NEW_SONG;
  const trimmedTitle = newTitle.trim();
  const derivedSlug = isAddingNew ? slugify(trimmedTitle) : "";
  const effectiveSlug = isAddingNew ? derivedSlug : songChoice;
  const effectiveTitle = isAddingNew
    ? trimmedTitle
    : songs.find((s) => s.slug === songChoice)?.title ?? "";

  const trimmedAuthor = author.trim();
  const authorSlug = trimmedAuthor.length === 0 ? "" : slugify(trimmedAuthor);
  const contributorValid = isSlug(contributor);
  const slugValid = isSlug(effectiveSlug);
  const titleValid = isAddingNew ? trimmedTitle.length > 0 : true;
  const authorValid = trimmedAuthor.length === 0 || authorSlug.length > 0;
  const styleValid = style !== "";
  const wavReady = wavBlob !== null;

  const canSubmit =
    contributorValid &&
    slugValid &&
    titleValid &&
    authorValid &&
    styleValid &&
    wavReady &&
    !submitting;

  const handleContributorChange = (value: string) => {
    setContributor(value);
    if (isSlug(value)) localStorage.setItem("simlabim.contributor", value);
  };

  const submit = async () => {
    if (!canSubmit || !wavBlob) return;
    setSubmitting(true);
    setError(null);
    try {
      const presign = await fetch("/api/upload-url", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ song_slug: effectiveSlug }),
      });
      if (!presign.ok) throw new Error(`Presign failed: ${presign.status}`);
      const { upload_url, take_id, storage_key } = (await presign.json()) as {
        upload_url: string;
        take_id: string;
        storage_key: string;
      };

      const put = await fetch(upload_url, {
        method: "PUT",
        headers: { "Content-Type": "audio/wav" },
        body: wavBlob,
      });
      if (!put.ok) throw new Error(`Upload failed: ${put.status}`);

      const finalize = await fetch("/api/takes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          song_slug: effectiveSlug,
          song_title: effectiveTitle,
          author: authorSlug || "unknown",
          contributor,
          style,
          storage_key,
          take_id,
          user_agent: navigator.userAgent,
        }),
      });
      const finalizeJson = (await finalize.json()) as {
        ok?: boolean;
        error?: string;
      };
      if (!finalize.ok || !finalizeJson.ok) {
        throw new Error(finalizeJson.error ?? `Finalize failed: ${finalize.status}`);
      }

      if (isAddingNew) {
        const refreshed = await fetch("/api/songs")
          .then((r) => r.json() as Promise<{ songs?: SongOption[] }>)
          .then((d) => d.songs ?? [])
          .catch(() => songs);
        setSongs(refreshed);
        setSongChoice(effectiveSlug);
        setNewTitle("");
      }

      setToast("Enviado! Obrigado");
      setTimeout(() => setToast(null), 2200);
      setWavBlob(null);
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Falha ao enviar");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-xl flex-col items-center px-4 pb-16 pt-10 text-center sm:pt-14 md:[zoom:1.1]">
      {/* Header */}
      <header
        className="reveal flex flex-col items-center gap-5"
        style={{ ["--reveal-index" as string]: 0 }}
      >
        <h1 className="text-[36px] font-semibold leading-[1.1] tracking-[-0.025em] sm:text-[48px]">
          Faça parte do treinamento do Simsalabim!
        </h1>
        <p className="max-w-[42ch] text-[16px] text-[color:var(--color-ink-muted)]">
          Ajude o Simsalabim a treinar e reconhecer músicas.
        </p>
      </header>

      <div className="h-7" />

      {/* Identity */}
      <section
        className="reveal flex w-full flex-col items-center gap-3"
        style={{ ["--reveal-index" as string]: 1 }}
      >
        <SectionTitle>Quem está gravando</SectionTitle>
        <label className="flex w-full flex-col items-center gap-2">
          <span className={labelClass}>Seu apelido</span>
          <input
            type="text"
            value={contributor}
            onChange={(e) => handleContributorChange(e.target.value.toLowerCase())}
            placeholder="ex: gustavo"
            className={inputClass}
          />
          {contributor.length > 0 && !contributorValid && (
            <Hint tone="red">Use apenas letras minúsculas, números e hífens.</Hint>
          )}
        </label>
      </section>

      <div className="h-7" />

      {/* Song */}
      <section
        className="reveal flex w-full flex-col items-center gap-3"
        style={{ ["--reveal-index" as string]: 2 }}
      >
        <SectionTitle>Qual música</SectionTitle>
        <div className="flex w-full flex-col items-center gap-2">
          <span className={labelClass}>Música</span>
          <SongPicker
            options={songs}
            value={songChoice}
            newSongValue={NEW_SONG}
            loading={!songsLoaded}
            onChange={(val) => {
              setSongChoice(val);
              if (val !== NEW_SONG) {
                setAuthor("");
                setNewTitle("");
              }
            }}
          />
        </div>

        {isAddingNew && (
          <label className="flex w-full flex-col items-center gap-2">
            <span className={labelClass}>Título da nova música</span>
            <input
              type="text"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              placeholder="ex: Meteoro"
              className={inputClass}
            />
            {trimmedTitle.length > 0 && derivedSlug.length === 0 && (
              <Hint tone="red">Título precisa conter letras ou números.</Hint>
            )}
          </label>
        )}

        {isAddingNew && (
          <label className="flex w-full flex-col items-center gap-2">
            <span className={labelClass}>Autor (opcional)</span>
            <input
              type="text"
              value={author}
              onChange={(e) => setAuthor(e.target.value)}
              placeholder="deixe em branco se não souber"
              className={inputClass}
            />
            {trimmedAuthor.length > 0 && !authorValid && (
              <Hint tone="red">Nome precisa conter letras ou números.</Hint>
            )}
          </label>
        )}
      </section>

      <div className="h-7" />

      {/* Style */}
      <section
        className="reveal flex w-full flex-col items-center gap-3"
        style={{ ["--reveal-index" as string]: 3 }}
      >
        <SectionTitle>Como vai gravar</SectionTitle>
        <div className="grid w-full grid-cols-1 gap-3 sm:grid-cols-3">
          {STYLES.map((s) => {
            const active = style === s;
            return (
              <button
                key={s}
                type="button"
                onClick={() => setStyle(s)}
                className={`flex flex-col items-center gap-1 rounded-lg border px-3 py-2.5 text-center transition-all duration-150 ${
                  active
                    ? "border-[color:var(--color-ink)] bg-[color:var(--color-ink)] text-white"
                    : "border-[var(--color-rule)] bg-white hover:border-[#cfcfcc]"
                }`}
              >
                <span className="text-[15px] font-medium leading-tight">
                  {STYLE_LABELS[s].split(" ")[0]}
                </span>
                <span
                  className={`text-[12px] leading-snug ${
                    active ? "text-white/70" : "text-[color:var(--color-ink-muted)]"
                  }`}
                >
                  {STYLE_HINTS[s]}
                </span>
              </button>
            );
          })}
        </div>
      </section>

      <div className="h-7" />

      {/* Record */}
      <section
        className="reveal flex w-full flex-col items-center gap-3"
        style={{ ["--reveal-index" as string]: 4 }}
      >
        <SectionTitle>Gravar</SectionTitle>
        <div className="w-full rounded-lg border border-[var(--color-rule)] bg-white p-3 sm:p-4">
          <Recorder onWavReady={setWavBlob} disabled={submitting} />
        </div>
      </section>

      <div className="h-7" />

      {/* Submit */}
      <section
        className="reveal flex w-full flex-col items-center gap-4"
        style={{ ["--reveal-index" as string]: 5 }}
      >
        <button
          type="button"
          onClick={submit}
          disabled={!canSubmit}
          className="group inline-flex items-center justify-center gap-2 rounded-full bg-[#346538] px-5 py-2.5 text-[14px] font-medium tracking-tight text-white transition-colors duration-150 hover:bg-[#2b5530] active:scale-[0.98] disabled:cursor-not-allowed disabled:bg-[#a8c0a8] disabled:text-white/90"
        >
          {submitting ? "Enviando…" : "Enviar"}
          <svg
            width="14"
            height="14"
            viewBox="0 0 16 16"
            fill="none"
            className="transition-transform duration-200 group-hover:translate-x-0.5"
            aria-hidden
          >
            <path
              d="M3 8h10m0 0L9 4m4 4l-4 4"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>

        {error && (
          <p className="w-full rounded-md border border-[#f3c8ca] bg-[var(--color-pastel-red-bg)] px-3 py-2 text-[13px] text-[color:var(--color-pastel-red-ink)]">
            {error}
          </p>
        )}

        <p className="max-w-[44ch] text-[12px] leading-relaxed text-[color:var(--color-ink-muted)]">
          Ao enviar, você concorda em contribuir esta gravação para o conjunto
          de dados de pesquisa.
        </p>
      </section>

      {/* Footer */}
      <footer className="mt-12 flex w-full flex-col items-center gap-1 text-[12px] text-[color:var(--color-ink-muted)]">
        <span>SimlabimAI</span>
        <span>Insper AI · 2026</span>
      </footer>

      {toast && (
        <div
          role="status"
          className="fixed bottom-6 left-1/2 -translate-x-1/2 rounded-full border border-[var(--color-rule)] bg-white px-3 py-2 text-[13px] font-medium text-[color:var(--color-ink)]"
          style={{ boxShadow: "0 2px 12px rgba(0,0,0,0.04)" }}
        >
          <span className="inline-flex items-center gap-2">
            <span
              aria-hidden
              className="inline-block h-1.5 w-1.5 rounded-full bg-[color:var(--color-pastel-green-ink)]"
            />
            {toast}
          </span>
        </div>
      )}
    </main>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-[20px] font-medium tracking-tight text-[color:var(--color-ink)]">
      {children}
    </h2>
  );
}

function Spacer() {
  return <div className="my-10 h-px w-12 bg-[var(--color-rule)]" />;
}

function Hint({
  children,
  tone = "muted",
}: {
  children: React.ReactNode;
  tone?: "muted" | "red";
}) {
  return (
    <span
      className={`text-[12px] leading-snug ${
        tone === "red"
          ? "text-[color:var(--color-pastel-red-ink)]"
          : "text-[color:var(--color-ink-muted)]"
      }`}
    >
      {children}
    </span>
  );
}
