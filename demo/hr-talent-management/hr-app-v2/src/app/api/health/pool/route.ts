import { NextResponse } from "next/server";
import { pool as pgPool } from "@/lib/postgres";
import { getPoolStats, healthCheck } from "@/lib/sf-client";
import { getSession } from "@/lib/session";

/**
 * Connection pool health (H3).
 * Reports Postgres and Snowflake pool state plus a live round-trip
 * probe, so pool exhaustion or a dead Snowflake session is visible
 * instead of surfacing as random query failures.
 */
export async function GET() {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "認証が必要です" }, { status: 401 });

  const sfStats = getPoolStats();

  const [sfProbe, pgProbe] = await Promise.all([
    healthCheck(),
    (async () => {
      const t0 = Date.now();
      try {
        await pgPool.query("SELECT 1");
        return { ok: true, latencyMs: Date.now() - t0 };
      } catch (err) {
        return { ok: false, latencyMs: Date.now() - t0, error: (err as Error).message };
      }
    })(),
  ]);

  const pgStats = {
    total: pgPool.totalCount,
    idle: pgPool.idleCount,
    waiting: pgPool.waitingCount,
  };

  const warnings: string[] = [];
  if (sfStats.busy >= sfStats.maxSize) {
    warnings.push(`Snowflakeプールが上限(${sfStats.maxSize})に達しています。待機中: ${sfStats.waiting}件`);
  }
  if (sfStats.down > 0) {
    warnings.push(`Snowflake接続 ${sfStats.down}件が切断状態です（次回取得時に再作成されます）`);
  }
  if (pgStats.waiting > 0) {
    warnings.push(`Postgres接続待ちが ${pgStats.waiting}件あります`);
  }
  if (sfProbe.latencyMs > 5000) {
    warnings.push(`Snowflakeの応答が遅延しています (${sfProbe.latencyMs}ms)`);
  }

  const healthy = sfProbe.ok && pgProbe.ok && warnings.length === 0;

  return NextResponse.json({
    checkedAt: new Date().toISOString(),
    healthy,
    warnings,
    warehouse: { pool: sfStats, probe: sfProbe },
    postgres: { pool: pgStats, probe: pgProbe },
  }, { status: healthy ? 200 : 503 });
}
