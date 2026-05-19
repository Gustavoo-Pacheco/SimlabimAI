import { config as loadEnv } from "dotenv";
loadEnv({ path: ".env.local" });
loadEnv({ path: ".env" });
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import postgres from "postgres";

async function main() {
  const url = process.env.DATABASE_URL;
  if (!url) throw new Error("DATABASE_URL not set");

  const sql = postgres(url, { prepare: false, max: 1 });
  const seed = readFileSync(resolve("drizzle/seed.sql"), "utf8");
  try {
    await sql.unsafe(seed);
    const rows = await sql<{ count: string }[]>`select count(*)::text as count from songs`;
    console.log(`Seed applied. songs.count = ${rows[0].count}`);
  } finally {
    await sql.end({ timeout: 1 });
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
