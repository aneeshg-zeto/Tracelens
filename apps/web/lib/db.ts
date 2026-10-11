import { Pool } from "pg";
import { env } from "@/lib/env";

const globalForPool = globalThis as unknown as { __tracelensPool?: Pool };

export function pool(): Pool {
  if (!globalForPool.__tracelensPool) {
    globalForPool.__tracelensPool = new Pool({
      connectionString: env().DATABASE_URL,
      max: 10,
      idleTimeoutMillis: 30_000,
      connectionTimeoutMillis: 5_000,
    });
  }
  return globalForPool.__tracelensPool;
}
