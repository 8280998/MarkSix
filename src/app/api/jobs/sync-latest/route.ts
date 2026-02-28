import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { loadDrawRecords } from "@/lib/data-source";
import { generatePredictionsForNextIssue, reviewIssue } from "@/lib/prediction-service";

function authorized(request: Request): boolean {
  const secret = process.env.CRON_SECRET;
  if (!secret) {
    return true;
  }

  const token = request.headers.get("x-cron-secret") ?? "";
  if (token === secret) {
    return true;
  }

  const auth = request.headers.get("authorization") ?? "";
  if (auth.toLowerCase().startsWith("bearer ")) {
    return auth.slice(7).trim() === secret;
  }

  return false;
}

export async function GET(request: Request) {
  try {
    if (!authorized(request)) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const records = await loadDrawRecords();

    let inserted = 0;
    let lastIssue = "";

    for (const r of records) {
      const created = await prisma.draw.upsert({
        where: { issueNo: r.issueNo },
        update: {
          drawDate: r.drawDate,
          numbersJson: JSON.stringify(r.numbers),
          specialNumber: r.specialNumber,
          source: process.env.RESULT_CSV_URL ? "remote_csv" : "local_csv",
        },
        create: {
          issueNo: r.issueNo,
          drawDate: r.drawDate,
          numbersJson: JSON.stringify(r.numbers),
          specialNumber: r.specialNumber,
          source: process.env.RESULT_CSV_URL ? "remote_csv" : "local_csv",
        },
        select: { issueNo: true, createdAt: true, updatedAt: true },
      });

      if (created.createdAt.getTime() === created.updatedAt.getTime()) {
        inserted += 1;
      }
      lastIssue = r.issueNo;
    }

    if (lastIssue) {
      await reviewIssue(lastIssue);
    }

    const nextIssue = await generatePredictionsForNextIssue();

    return NextResponse.json({
      ok: true,
      totalRecords: records.length,
      inserted,
      reviewedIssue: lastIssue,
      generatedForIssue: nextIssue,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
