import { PredictionStatus, type Draw } from "@prisma/client";
import { prisma } from "@/lib/prisma";
import { allStrategies, generateStrategyResult } from "@/lib/strategies";
import { type StrategyId } from "@/lib/types";

function nextIssueNo(issueNo: string): string {
  const [year, no] = issueNo.split("/");
  const seq = Number(no);
  if (!year || Number.isNaN(seq)) {
    return issueNo;
  }
  return `${year}/${String(seq + 1).padStart(no.length, "0")}`;
}

function parseNumbers(draw: Draw): number[] {
  return JSON.parse(draw.numbersJson) as number[];
}

export async function generatePredictionsForIssue(issueNo: string, strategyIds?: StrategyId[]) {
  const draws = await prisma.draw.findMany({
    orderBy: { drawDate: "desc" },
    take: 200,
  });

  if (draws.length < 20) {
    throw new Error("Not enough history to generate predictions");
  }

  const strategyList = strategyIds ?? allStrategies();
  const createdRuns: number[] = [];

  for (const strategy of strategyList) {
    const result = generateStrategyResult(strategy, draws);

    const run = await prisma.predictionRun.upsert({
      where: {
        issueNo_strategy_strategyVersion: {
          issueNo,
          strategy: result.strategy,
          strategyVersion: result.strategyVersion,
        },
      },
      update: {
        createdAt: new Date(),
        status: PredictionStatus.PENDING,
        hitCount: null,
        hitRate: null,
        reviewedAt: null,
      },
      create: {
        issueNo,
        strategy: result.strategy,
        strategyVersion: result.strategyVersion,
      },
      select: { id: true },
    });

    await prisma.predictionPick.deleteMany({ where: { runId: run.id } });
    await prisma.predictionPick.createMany({
      data: result.picks.map((pick) => ({
        runId: run.id,
        number: pick.number,
        rank: pick.rank,
        score: pick.score,
        reason: pick.reason,
      })),
    });

    createdRuns.push(run.id);
  }

  return createdRuns;
}

export async function generatePredictionsForNextIssue() {
  const latest = await prisma.draw.findFirst({
    orderBy: { drawDate: "desc" },
    select: { issueNo: true },
  });

  if (!latest) {
    throw new Error("No draw history available");
  }

  const targetIssue = nextIssueNo(latest.issueNo);
  await generatePredictionsForIssue(targetIssue);
  return targetIssue;
}

export async function reviewIssue(issueNo: string) {
  const draw = await prisma.draw.findUnique({ where: { issueNo } });
  if (!draw) {
    return { reviewed: 0 };
  }

  const winning = new Set(parseNumbers(draw));
  const pendingRuns = await prisma.predictionRun.findMany({
    where: { issueNo, status: PredictionStatus.PENDING },
    include: { picks: true },
  });

  for (const run of pendingRuns) {
    const matched = run.picks
      .map((p) => p.number)
      .filter((n) => winning.has(n))
      .sort((a, b) => a - b);

    const hitCount = matched.length;
    const hitRate = Number((hitCount / 6).toFixed(4));

    await prisma.predictionRun.update({
      where: { id: run.id },
      data: {
        status: PredictionStatus.REVIEWED,
        hitCount,
        hitRate,
        reviewedAt: new Date(),
      },
    });

    await prisma.predictionReview.upsert({
      where: { runId: run.id },
      update: {
        matchedNumbersJson: JSON.stringify(matched),
        hitCount,
        hitRate,
      },
      create: {
        runId: run.id,
        drawId: draw.id,
        matchedNumbersJson: JSON.stringify(matched),
        hitCount,
        hitRate,
      },
    });
  }

  return { reviewed: pendingRuns.length };
}
