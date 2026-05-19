import { NextResponse } from "next/server";
import { getDb } from "@/lib/db";
import { songs } from "@/lib/db/schema";

export async function GET() {
  try {
    const db = getDb();
    const rows = await db
      .select({ slug: songs.slug, title: songs.title, author: songs.author })
      .from(songs)
      .orderBy(songs.title);
    return NextResponse.json({ songs: rows });
  } catch (err) {
    console.error("GET /api/songs failed", err);
    return NextResponse.json({ error: "internal" }, { status: 500 });
  }
}
