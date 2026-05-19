import { drizzle } from "drizzle-orm/postgres-js";
import postgres from "postgres";
import * as schema from "./schema";

type Sql = ReturnType<typeof postgres>;

declare global {
  // eslint-disable-next-line no-var
  var __sim_pg__: Sql | undefined;
}

function getSql(): Sql {
  const url = process.env.DATABASE_URL;
  if (!url) {
    throw new Error("DATABASE_URL not set");
  }
  if (!globalThis.__sim_pg__) {
    // Pool sized for serverless / Fluid Compute. `prepare: false` for pgbouncer transaction mode.
    globalThis.__sim_pg__ = postgres(url, { prepare: false, max: 5 });
  }
  return globalThis.__sim_pg__;
}

export function getDb() {
  return drizzle(getSql(), { schema });
}

export { schema };
