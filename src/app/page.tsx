import { prisma } from "@/lib/prisma";
import { strategyMeta } from "@/lib/strategies";

function parseJsonArray(text: string): number[] {
  try {
    return JSON.parse(text) as number[];
  } catch {
    return [];
  }
}

export default async function HomePage() {
  const latestDraw = await prisma.draw.findFirst({
    orderBy: { drawDate: "desc" },
  });

  const pendingRuns = await prisma.predictionRun.findMany({
    where: { status: "PENDING" },
    include: { picks: { orderBy: { rank: "asc" } } },
    orderBy: [{ issueNo: "desc" }, { createdAt: "desc" }],
    take: 8,
  });

  return (
    <section>
      <h2>最新预测</h2>
      {latestDraw ? (
        <p className="kv">
          最近一期: {latestDraw.issueNo} ({latestDraw.drawDate.toISOString().slice(0, 10)}) | 开奖号码:
          {" "}
          {parseJsonArray(latestDraw.numbersJson).join(", ")} + 特别号 {latestDraw.specialNumber}
        </p>
      ) : (
        <p className="kv">暂无历史数据，请先运行 `npm run bootstrap:history`。</p>
      )}

      <div className="grid">
        {pendingRuns.map((run) => (
          <article key={run.id} className="card">
            <h3>{strategyMeta[run.strategy as keyof typeof strategyMeta]?.name ?? run.strategy}</h3>
            <p className="kv">目标期号: {run.issueNo}</p>
            <div className="numbers">
              {run.picks.map((pick) => (
                <span key={pick.id} className="ball">
                  {String(pick.number).padStart(2, "0")}
                </span>
              ))}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
