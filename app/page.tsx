"use client";

import { useEffect, useMemo, useState } from "react";
import Recorder from "@/components/Recorder";
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

const NEW_SONG = "__new__";

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

      // refresh song list to include any newly added entry
      if (isAddingNew) {
        const refreshed = await fetch("/api/songs")
          .then((r) => r.json() as Promise<{ songs?: SongOption[] }>)
          .then((d) => d.songs ?? [])
          .catch(() => songs);
        setSongs(refreshed);
        setSongChoice(effectiveSlug);
        setNewTitle("");
      }

      setToast("Enviado!");
      setTimeout(() => setToast(null), 2000);
      setWavBlob(null);
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Falha ao enviar");
    } finally {
      setSubmitting(false);
    }
  };

  const songOptions = useMemo(
    () =>
      songs.map((s) => (
        <option key={s.slug} value={s.slug}>
          {s.title}
          {s.author !== "unknown" ? ` — ${s.author}` : ""}
        </option>
      )),
    [songs],
  );

  return (
    <main className="mx-auto flex max-w-md flex-col gap-6 p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold">SimlabimAI</h1>
        <p className="text-sm text-neutral-500">
          Ao enviar, você concorda em contribuir esta gravação para o conjunto
          de dados de pesquisa.
        </p>
      </header>

      <label className="flex flex-col gap-1">
        <span className="text-sm font-medium">Seu apelido</span>
        <input
          type="text"
          value={contributor}
          onChange={(e) => handleContributorChange(e.target.value.toLowerCase())}
          placeholder="ex: gustavo"
          className="rounded-md border border-neutral-300 px-3 py-2 text-sm"
        />
        {contributor.length > 0 && !contributorValid && (
          <span className="text-xs text-red-600">
            Use apenas letras minúsculas, números e hífens.
          </span>
        )}
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-sm font-medium">Música</span>
        <select
          value={songChoice}
          onChange={(e) => setSongChoice(e.target.value)}
          className="rounded-md border border-neutral-300 px-3 py-2 text-sm"
          disabled={!songsLoaded}
        >
          <option value="" disabled>
            {songsLoaded ? "Selecione…" : "Carregando…"}
          </option>
          {songOptions}
          <option value={NEW_SONG}>+ Adicionar nova música</option>
        </select>
      </label>

      {isAddingNew && (
        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium">Título da música</span>
          <input
            type="text"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            placeholder="ex: Meteoro"
            className="rounded-md border border-neutral-300 px-3 py-2 text-sm"
          />
          {trimmedTitle.length > 0 && derivedSlug.length > 0 && (
            <span className="text-xs text-neutral-500">
              Identificador: <code>{derivedSlug}</code>
            </span>
          )}
          {trimmedTitle.length > 0 && derivedSlug.length === 0 && (
            <span className="text-xs text-red-600">
              Título precisa conter letras ou números.
            </span>
          )}
        </label>
      )}

      <label className="flex flex-col gap-1">
        <span className="text-sm font-medium">Autor da música</span>
        <input
          type="text"
          value={author}
          onChange={(e) => setAuthor(e.target.value)}
          placeholder="deixe em branco se não souber"
          className="rounded-md border border-neutral-300 px-3 py-2 text-sm"
        />
        {trimmedAuthor.length > 0 && authorSlug.length > 0 && (
          <span className="text-xs text-neutral-500">
            Identificador: <code>{authorSlug}</code>
          </span>
        )}
        {trimmedAuthor.length > 0 && !authorValid && (
          <span className="text-xs text-red-600">
            Nome precisa conter letras ou números.
          </span>
        )}
      </label>

      <fieldset className="flex flex-col gap-2">
        <legend className="text-sm font-medium">Como você vai gravar</legend>
        <div className="grid grid-cols-3 gap-2">
          {STYLES.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setStyle(s)}
              className={`rounded-md border px-3 py-2 text-xs ${
                style === s
                  ? "border-neutral-900 bg-neutral-900 text-white"
                  : "border-neutral-300 bg-white hover:bg-neutral-100"
              }`}
            >
              {STYLE_LABELS[s]}
            </button>
          ))}
        </div>
      </fieldset>

      <Recorder onWavReady={setWavBlob} disabled={submitting} />

      <button
        type="button"
        onClick={submit}
        disabled={!canSubmit}
        className="rounded-md bg-emerald-600 px-4 py-3 text-sm font-medium text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {submitting ? "Enviando…" : "Enviar"}
      </button>

      {error && (
        <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white shadow-lg">
          {toast}
        </div>
      )}
    </main>
  );
}
