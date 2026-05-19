import { createClient, type SupabaseClient } from "@supabase/supabase-js";

let cached: SupabaseClient | null = null;

function readEnv(): { url: string; secret: string; bucket: string } {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL ?? process.env.SUPABASE_URL;
  const secret =
    process.env.SUPABASE_SECRET_KEY ?? process.env.SUPABASE_SERVICE_ROLE_KEY;
  const bucket = process.env.SUPABASE_BUCKET ?? "audio";
  if (!url || !secret) {
    throw new Error(
      "Missing Supabase env vars: need NEXT_PUBLIC_SUPABASE_URL and SUPABASE_SECRET_KEY (service_role).",
    );
  }
  return { url, secret, bucket };
}

function getAdminClient(): { client: SupabaseClient; bucket: string } {
  const { url, secret, bucket } = readEnv();
  if (!cached) {
    cached = createClient(url, secret, {
      auth: { persistSession: false, autoRefreshToken: false },
    });
  }
  return { client: cached, bucket };
}

/**
 * Returns a Supabase signed upload URL. The client PUTs the body directly to
 * `signedUrl` (no extra headers needed — the token is in the URL).
 */
export async function createSignedUploadUrl(
  key: string,
): Promise<{ uploadUrl: string; path: string }> {
  const { client, bucket } = getAdminClient();
  const { data, error } = await client.storage
    .from(bucket)
    .createSignedUploadUrl(key);
  if (error || !data) {
    throw new Error(`createSignedUploadUrl failed: ${error?.message ?? "unknown"}`);
  }
  return { uploadUrl: data.signedUrl, path: data.path };
}

/**
 * Downloads an object's bytes. Returns null when the object isn't found.
 * Replaces the previous separate headObject + getObjectBytes flow — one
 * roundtrip, and we already need the bytes for SHA-256 + WAV parsing.
 */
export async function downloadObject(key: string): Promise<Uint8Array | null> {
  const { client, bucket } = getAdminClient();
  const { data, error } = await client.storage.from(bucket).download(key);
  if (error) {
    const status = (error as { status?: number }).status;
    if (status === 404) return null;
    const message = (error as Error).message ?? String(error);
    if (/not.?found|does not exist/i.test(message)) return null;
    throw new Error(`download failed: ${message}`);
  }
  if (!data) return null;
  return new Uint8Array(await data.arrayBuffer());
}
