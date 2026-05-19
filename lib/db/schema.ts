import {
  pgTable,
  serial,
  integer,
  text,
  bigint,
  real,
  index,
  uniqueIndex,
} from "drizzle-orm/pg-core";

export const songs = pgTable(
  "songs",
  {
    id: serial("id").primaryKey(),
    slug: text("slug").notNull(),
    title: text("title").notNull(),
    author: text("author").notNull().default("unknown"),
    createdAt: bigint("created_at", { mode: "number" }).notNull(),
  },
  (t) => ({
    slugUnique: uniqueIndex("songs_slug_unique").on(t.slug),
  }),
);

export const takes = pgTable(
  "takes",
  {
    id: text("id").primaryKey(),
    songId: integer("song_id")
      .notNull()
      .references(() => songs.id),
    contributor: text("contributor").notNull(),
    storageKey: text("storage_key").notNull(),
    durationS: real("duration_s"),
    style: text("style").notNull(),
    audioSha256: text("audio_sha256").notNull(),
    userAgent: text("user_agent"),
    status: text("status").notNull().default("pending"),
    reviewNote: text("review_note"),
    reviewedAt: bigint("reviewed_at", { mode: "number" }),
    createdAt: bigint("created_at", { mode: "number" }).notNull(),
  },
  (t) => ({
    storageKeyUnique: uniqueIndex("takes_storage_key_unique").on(t.storageKey),
    dedupIdx: index("takes_song_contributor_created_idx").on(
      t.songId,
      t.contributor,
      t.createdAt,
    ),
  }),
);

export type Song = typeof songs.$inferSelect;
export type Take = typeof takes.$inferSelect;
