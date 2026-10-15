import { cookies } from "next/headers";

export async function getDataPath(): Promise<"warehouse" | "pg_lake"> {
  const store = await cookies();
  return (store.get("data_path")?.value as "warehouse" | "pg_lake") || "pg_lake";
}

export function isPgLake(path: string): boolean {
  return path === "pg_lake";
}
