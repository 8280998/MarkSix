import { NextResponse } from "next/server";
import { generatePredictionsForIssue, generatePredictionsForNextIssue } from "@/lib/prediction-service";
import { type StrategyId } from "@/lib/types";

export async function POST(request: Request) {
  try {
    const body = (await request.json().catch(() => ({}))) as {
      issueNo?: string;
      strategies?: StrategyId[];
    };

    if (body.issueNo) {
      const createdRunIds = await generatePredictionsForIssue(body.issueNo, body.strategies);
      return NextResponse.json({ ok: true, issueNo: body.issueNo, createdRunIds });
    }

    const issueNo = await generatePredictionsForNextIssue();
    return NextResponse.json({ ok: true, issueNo });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
