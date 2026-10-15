import { NextResponse } from "next/server";
import { deleteSessionCookie } from "@/lib/session";

export async function POST() {
  const response = NextResponse.json({ success: true });
  const { name, options } = deleteSessionCookie();
  response.cookies.set(name, "", options);
  return response;
}
