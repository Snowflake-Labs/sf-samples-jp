import sdk from "snowflake-sdk";
import fs from "fs";

sdk.configure({ logLevel: "ERROR" });

const POOL_SIZE = 4;
const CONNECT_TIMEOUT = 15000;
const CONNECTION_TTL = 3600000;
const SPCS_TOKEN_PATH = "/snowflake/session/token";

const VALID_ROLES = new Set(["HR_ADMIN_ROLE", "HR_MANAGER_ROLE", "HR_VIEWER_ROLE", "HR_SERVICE_ROLE", "ACCOUNTADMIN"]);

let cachedSpcsToken: { value: string; readAt: number } | null = null;
const TOKEN_CACHE_TTL = 30000;

function isRunningInSpcs(): boolean {
  try {
    return fs.existsSync(SPCS_TOKEN_PATH);
  } catch {
    return false;
  }
}

export function getSpcsToken(): string {
  if (cachedSpcsToken && Date.now() - cachedSpcsToken.readAt < TOKEN_CACHE_TTL) {
    return cachedSpcsToken.value;
  }
  try {
    const value = fs.readFileSync(SPCS_TOKEN_PATH, "utf-8").trim();
    cachedSpcsToken = { value, readAt: Date.now() };
    return value;
  } catch {
    return "";
  }
}

function getConfig(): sdk.ConnectionOptions {
  const pat = process.env.SNOWFLAKE_PAT || process.env.SNOWFLAKE_PASSWORD || "";

  const spcs = isRunningInSpcs();
  const spcsHost = process.env.SNOWFLAKE_HOST || "";

  if (spcs && !pat) {
    return {
      accessUrl: "https://" + spcsHost,
      host: spcsHost,
      account: process.env.SNOWFLAKE_ACCOUNT || "",
      authenticator: "OAUTH",
      token: getSpcsToken(),
      warehouse: process.env.SNOWFLAKE_WAREHOUSE || "HR_APP_WH",
      database: process.env.SNOWFLAKE_DATABASE || "HR_ANALYTICS",
      schema: process.env.SNOWFLAKE_SCHEMA || "STAGING",
      clientSessionKeepAlive: true,
      clientSessionKeepAliveHeartbeatFrequency: 900,
    };
  }

  if (spcs && pat) {
    return {
      accessUrl: "https://" + spcsHost,
      host: spcsHost,
      account: process.env.SNOWFLAKE_ACCOUNT || "",
      username: process.env.SNOWFLAKE_USER || "",
      authenticator: "PROGRAMMATIC_ACCESS_TOKEN",
      token: pat,
      role: process.env.SNOWFLAKE_ROLE || "ACCOUNTADMIN",
      warehouse: process.env.SNOWFLAKE_WAREHOUSE || "HR_APP_WH",
      database: process.env.SNOWFLAKE_DATABASE || "HR_ANALYTICS",
      schema: process.env.SNOWFLAKE_SCHEMA || "STAGING",
      clientSessionKeepAlive: true,
      clientSessionKeepAliveHeartbeatFrequency: 900,
    };
  }

  return {
    account: process.env.SNOWFLAKE_ACCOUNT || "",
    username: process.env.SNOWFLAKE_USER || "",
    authenticator: "PROGRAMMATIC_ACCESS_TOKEN",
    token: pat,
    role: process.env.SNOWFLAKE_ROLE || "ACCOUNTADMIN",
    warehouse: process.env.SNOWFLAKE_WAREHOUSE || "HR_APP_WH",
    database: process.env.SNOWFLAKE_DATABASE || "HR_ANALYTICS",
    schema: process.env.SNOWFLAKE_SCHEMA || "STAGING",
    clientSessionKeepAlive: true,
    clientSessionKeepAliveHeartbeatFrequency: 900,
  };
}

interface PooledConnection {
  conn: sdk.Connection;
  busy: boolean;
  createdAt: number;
}

const pool: PooledConnection[] = [];
let initPromise: Promise<void> | null = null;
const waitQueue: Array<(pc: PooledConnection) => void> = [];

async function createConnection(): Promise<sdk.Connection> {
  const conn = sdk.createConnection(getConfig());
  return new Promise<sdk.Connection>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("Connection timeout")), CONNECT_TIMEOUT);
    conn.connect((err) => {
      clearTimeout(timer);
      if (err) reject(err);
      else resolve(conn);
    });
  });
}

async function initPool(): Promise<void> {
  if (initPromise) return initPromise;
  initPromise = (async () => {
    try {
      const conn = await createConnection();
      pool.push({ conn, busy: false, createdAt: Date.now() });
    } finally {
      initPromise = null;
    }
  })();
  return initPromise;
}

function isStale(pc: PooledConnection): boolean {
  return Date.now() - pc.createdAt > CONNECTION_TTL;
}

async function acquire(): Promise<PooledConnection> {
  const free = pool.find((p) => !p.busy && !isStale(p));
  if (free) {
    // Verify the connection is still usable before handing it out.
    // A pooled connection can be dropped server-side (idle timeout, restart)
    // while still looking healthy locally, which surfaces as a failed query.
    if (!free.conn.isUp()) {
      removeFromPool(free);
      try { free.conn.destroy(() => {}); } catch { /* ignore */ }
      return acquire();
    }
    free.busy = true;
    return free;
  }

  const stale = pool.find((p) => !p.busy && isStale(p));
  if (stale) {
    removeFromPool(stale);
    try { stale.conn.destroy(() => {}); } catch { /* ignore */ }
  }

  if (pool.length < POOL_SIZE) {
    try {
      const conn = await createConnection();
      const pc: PooledConnection = { conn, busy: true, createdAt: Date.now() };
      pool.push(pc);
      return pc;
    } catch {
      // fall through to wait
    }
  }

  return new Promise<PooledConnection>((resolve) => {
    waitQueue.push(resolve);
  });
}

/**
 * Pool statistics for the health endpoint (H3).
 */
export function getPoolStats(): {
  size: number;
  maxSize: number;
  busy: number;
  idle: number;
  stale: number;
  down: number;
  waiting: number;
  connectionTtlMs: number;
} {
  let busy = 0, idle = 0, staleCount = 0, down = 0;
  for (const pc of pool) {
    if (pc.busy) busy++; else idle++;
    if (isStale(pc)) staleCount++;
    try { if (!pc.conn.isUp()) down++; } catch { down++; }
  }
  return {
    size: pool.length,
    maxSize: POOL_SIZE,
    busy,
    idle,
    stale: staleCount,
    down,
    waiting: waitQueue.length,
    connectionTtlMs: CONNECTION_TTL,
  };
}

/**
 * Round-trip health probe. Runs a trivial query through the pool
 * and reports latency so the endpoint can distinguish "pool has
 * connections" from "Snowflake actually answers".
 */
export async function healthCheck(): Promise<{ ok: boolean; latencyMs: number; error?: string }> {
  const t0 = Date.now();
  try {
    await query<{ ONE: number }>(`SELECT 1 AS ONE`);
    return { ok: true, latencyMs: Date.now() - t0 };
  } catch (err) {
    return { ok: false, latencyMs: Date.now() - t0, error: (err as Error).message };
  }
}

/**
 * Close every pooled connection. Intended for graceful shutdown.
 */
export async function closePool(): Promise<void> {
  const all = [...pool];
  pool.length = 0;
  waitQueue.length = 0;
  await Promise.all(
    all.map(
      (pc) =>
        new Promise<void>((resolve) => {
          try {
            pc.conn.destroy(() => resolve());
          } catch {
            resolve();
          }
        })
    )
  );
}

function release(pc: PooledConnection): void {
  pc.busy = false;
  if (isStale(pc)) {
    removeFromPool(pc);
    try { pc.conn.destroy(() => {}); } catch { /* ignore */ }
    drainWaitQueue();
    return;
  }
  const waiter = waitQueue.shift();
  if (waiter) {
    pc.busy = true;
    waiter(pc);
  }
}

function removeFromPool(pc: PooledConnection): void {
  const idx = pool.indexOf(pc);
  if (idx >= 0) pool.splice(idx, 1);
}

function drainWaitQueue(): void {
  if (waitQueue.length > 0 && pool.length < POOL_SIZE) {
    createConnection()
      .then((conn) => {
        const pc: PooledConnection = { conn, busy: true, createdAt: Date.now() };
        pool.push(pc);
        const waiter = waitQueue.shift();
        if (waiter) {
          waiter(pc);
        } else {
          pc.busy = false;
        }
      })
      .catch(() => {
        const waiter = waitQueue.shift();
        if (waiter) {
          acquire().then(waiter);
        }
      });
  }
}

export async function query<T>(sql: string, binds?: sdk.Binds): Promise<T[]> {
  if (pool.length === 0) await initPool();

  const pc = await acquire();
  try {
    return await new Promise<T[]>((resolve, reject) => {
      pc.conn.execute({
        sqlText: sql,
        binds,
        complete: (err, _stmt, rows) => {
          if (err) reject(err);
          else resolve((rows || []) as T[]);
        },
      });
    });
  } catch (err) {
    console.error("Query error:", (err as Error).message);
    removeFromPool(pc);
    drainWaitQueue();
    throw err;
  } finally {
    if (pool.includes(pc)) release(pc);
  }
}

export async function queryWithRole<T>(sql: string, role: string): Promise<T[]> {
  if (!VALID_ROLES.has(role)) {
    throw new Error(`Invalid role: ${role}`);
  }
  if (pool.length === 0) await initPool();

  const pc = await acquire();
  try {
    await new Promise<void>((resolve, reject) => {
      pc.conn.execute({
        sqlText: `USE ROLE ${role}`,
        complete: (err) => {
          if (err) reject(err);
          else resolve();
        },
      });
    });
    return await new Promise<T[]>((resolve, reject) => {
      pc.conn.execute({
        sqlText: sql,
        complete: (err, _stmt, rows) => {
          if (err) reject(err);
          else resolve((rows || []) as T[]);
        },
      });
    });
  } catch (err) {
    console.error("Query error:", (err as Error).message);
    removeFromPool(pc);
    drainWaitQueue();
    throw err;
  } finally {
    if (pool.includes(pc)) release(pc);
  }
}
