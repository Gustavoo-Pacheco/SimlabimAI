import { NextResponse } from "next/server";
import { and, desc, eq, gte } from "drizzle-orm";
import { assertSlug, assertStyle, BadInput, isSlug } from "@/lib/slugs";
import { downloadObject } from "@/lib/storage";
import { parseWavHeader } from "@/lib/wav";
import { getDb } from "@/lib/db";
import { takes } from "@/lib/db/schema";
import { upsertSong } from "@/lib/upsert-author";

const MIN_BYTES = 8 * 1024;
const MAX_BYTES = 40 * 1024 * 1024;
const DEDUP_WINDOW_MS = 5_000;
const UA_MAX = 512;

async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const data = bytes.buffer.slice(
    bytes.byteOffset,
    bytes.byteOffset + bytes.byteLength,
  ) as ArrayBuffer;
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export async function POST(req: Request) {
  try {
    const body = (await req.json()) as {
      song_slug?: unknown;
      song_title?: unknown;
      author?: unknown;
      contributor?: unknown;
      style?: unknown;
      storage_key?: unknown;
      take_id?: unknown;
      user_agent?: unknown;
    };

    const songSlug = assertSlug(body.song_slug, "song_slug");
    const contributor = assertSlug(body.contributor, "contributor");
    const style = assertStyle(body.style);

    const rawAuthor =
      typeof body.author === "string" && body.author.trim().length > 0
        ? body.author.trim()
        : "unknown";
    if (rawAuthor !== "unknown" && !isSlug(rawAuthor)) {
      throw new BadInput("author must be a slug or empty");
    }

    const takeId = typeof body.take_id === "string" ? body.take_id : "";
    if (!/^[0-9a-f-]{36}$/i.test(takeId)) {
      throw new BadInput("take_id must be a uuid");
    }

    const expectedKey = `raw_audio/${songSlug}/${takeId}.wav`;
    if (body.storage_key !== expectedKey) {
      throw new BadInput("storage_key does not match song_slug + take_id");
    }

    const bytes = await downloadObject(expectedKey);
    if (!bytes) {
      throw new BadInput("uploaded object not found in storage");
    }
    if (bytes.byteLength < MIN_BYTES || bytes.byteLength > MAX_BYTES) {
      throw new BadInput(
        `object size ${bytes.byteLength} outside [${MIN_BYTES}, ${MAX_BYTES}]`,
      );
    }

    const wav = parseWavHeader(bytes);
    const audioSha256 = await sha256Hex(bytes);

    const songTitle =
      typeof body.song_title === "string" && body.song_title.trim().length > 0
        ? body.song_title.trim().slice(0, 200)
        : songSlug;

    const song = await upsertSong(songSlug, songTitle, rawAuthor);

    const db = getDb();
    const now = Date.now();
    const cutoff = now - DEDUP_WINDOW_MS;
    const recent = await db
      .select({ id: takes.id, createdAt: takes.createdAt })
      .from(takes)
      .where(
        and(
          eq(takes.songId, song.id),
          eq(takes.contributor, contributor),
          gte(takes.createdAt, cutoff),
        ),
      )
      .orderBy(desc(takes.createdAt))
      .limit(1);
    if (recent.length > 0) {
      return NextResponse.json(
        { error: "duplicate submission within 5s" },
        { status: 409 },
      );
    }

    const userAgent =
      typeof body.user_agent === "string"
        ? body.user_agent.slice(0, UA_MAX)
        : null;

    await db.insert(takes).values({
      id: takeId,
      songId: song.id,
      contributor,
      storageKey: expectedKey,
      durationS: wav.durationSeconds,
      style,
      audioSha256,
      userAgent,
      status: "pending",
      createdAt: now,
    });

    return NextResponse.json({ ok: true, take_id: takeId });
  } catch (err) {
    if (err instanceof BadInput) {
      return NextResponse.json({ error: err.message }, { status: 400 });
    }
    console.error("POST /api/takes failed", err);
    return NextResponse.json({ error: "internal" }, { status: 500 });
  }
}
