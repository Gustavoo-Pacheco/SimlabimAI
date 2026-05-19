import { sql } from "drizzle-orm";
import { getDb } from "./db";
import { songs } from "./db/schema";
import authors from "@shared/authors.json";

const UNKNOWN = authors.unknownSentinel;

/**
 * Upserts a song by slug. The author-merge rule:
 *   - if `newAuthor` is "unknown" and an existing row has a real value, keep the existing value
 *   - if the row doesn't exist, insert with `newAuthor`
 *   - title only gets stored on insert; existing rows keep their title
 *
 * Implemented via ON CONFLICT(slug) DO UPDATE with the COALESCE/NULLIF expression
 * from CLAUDE.md so the rule lives in exactly one place.
 */
export async function upsertSong(
  slug: string,
  title: string,
  newAuthor: string,
): Promise<{ id: number; slug: string; title: string; author: string }> {
  const db = getDb();
  const now = Date.now();
  const rows = await db
    .insert(songs)
    .values({ slug, title, author: newAuthor, createdAt: now })
    .onConflictDoUpdate({
      target: songs.slug,
      set: {
        author: sql`COALESCE(NULLIF(excluded.author, ${UNKNOWN}), ${songs.author}, excluded.author)`,
      },
    })
    .returning();

  const row = rows[0];
  return { id: row.id, slug: row.slug, title: row.title, author: row.author };
}
