import { NextResponse } from "next/server";

import { prisma } from "@/lib/prisma";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Liveness + DB connectivity check. Returns 200 when the DB answers, 503 otherwise.
export async function GET() {
  try {
    const rows = await prisma.$queryRaw<{ ok: number }[]>`SELECT 1 AS ok`;
    return NextResponse.json({ status: "ok", db: rows?.[0]?.ok === 1 });
  } catch (err) {
    return NextResponse.json(
      { status: "error", db: false, error: String(err) },
      { status: 503 },
    );
  }
}
