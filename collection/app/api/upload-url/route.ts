import { NextResponse } from "next/server";
import { assertSlug, BadInput } from "@/lib/slugs";
import { createSignedUploadUrl } from "@/lib/storage";

export async function POST(req: Request) {
  try {
    const body = (await req.json()) as { song_slug?: unknown };
    const songSlug = assertSlug(body.song_slug, "song_slug");

    const takeId = crypto.randomUUID();
    const storageKey = `raw_audio/${songSlug}/${takeId}.wav`;
    const { uploadUrl } = await createSignedUploadUrl(storageKey);

    return NextResponse.json({
      upload_url: uploadUrl,
      take_id: takeId,
      storage_key: storageKey,
    });
  } catch (err) {
    if (err instanceof BadInput) {
      return NextResponse.json({ error: err.message }, { status: 400 });
    }
    console.error("POST /api/upload-url failed", err);
    return NextResponse.json({ error: "internal" }, { status: 500 });
  }
}
