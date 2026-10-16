import { NextResponse } from "next/server";
import { query } from "@/lib/sf-client";
import { getSession } from "@/lib/session";

export async function GET() {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  try {
    const results = await query<{
      QUERY_TIME: string;
      USER_NAME: string;
      TABLE_NAME: string;
      COLUMNS_ACCESSED: string;
      QUERY_ID: string;
    }>(`
      SELECT
        TO_CHAR(h.QUERY_START_TIME, 'YYYY-MM-DD HH24:MI:SS') AS QUERY_TIME,
        h.USER_NAME,
        obj.value:objectName::STRING AS TABLE_NAME,
        ARRAY_TO_STRING(
          ARRAY_AGG(DISTINCT col.value:columnName::STRING) WITHIN GROUP (ORDER BY col.value:columnName::STRING),
          ', '
        ) AS COLUMNS_ACCESSED,
        h.QUERY_ID
      FROM SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY h,
        LATERAL FLATTEN(input => h.DIRECT_OBJECTS_ACCESSED) obj,
        LATERAL FLATTEN(input => obj.value:columns) col
      WHERE h.QUERY_START_TIME > DATEADD('day', -7, CURRENT_TIMESTAMP())
        AND obj.value:objectName::STRING LIKE 'HR_ANALYTICS%'
      GROUP BY h.QUERY_START_TIME, h.USER_NAME, obj.value:objectName::STRING, h.QUERY_ID
      ORDER BY h.QUERY_START_TIME DESC
      LIMIT 50
    `);

    return NextResponse.json(results);
  } catch (error) {
    console.error("Access history error:", error);
    return NextResponse.json(
      { error: "Failed to fetch access history" },
      { status: 500 }
    );
  }
}
