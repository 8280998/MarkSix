import { prisma } from "@/lib/prisma";

function parseJsonArray(text: string): number[] {
  try {
    return JSON.parse(text) as number[];
  } catch {
    return [];
  }
}

export default async function ReviewPage() {
  const reviews = await prisma.predictionReview.findMany({
    include: {
      run: true,
      draw: true,
    },
    orderBy: { createdAt: "desc" },
    take: 50,
  });

  const stats = await prisma.predictionRun.groupBy({
    by: ["strategy"],
    where: { status: "REVIEWED" },
    _avg: { hitRate: true, hitCount: true },
    _count: { _all: true },
  });

  return (
    <section>
      <h2>策略复盘</h2>
      <p className="kv">按期次显示命中号码和命中率，便于跟踪各方案稳定性。</p>

      <h3>策略总览</h3>
      <table>
        <thead>
          <tr>
            <th>策略</th>
            <th>复盘次数</th>
            <th>平均命中数</th>
            <th>平均命中率</th>
          </tr>
        </thead>
        <tbody>
          {stats.map((s) => (
            <tr key={s.strategy}>
              <td>{s.strategy}</td>
              <td>{s._count._all}</td>
              <td>{(s._avg.hitCount ?? 0).toFixed(2)}</td>
              <td>{((s._avg.hitRate ?? 0) * 100).toFixed(2)}%</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3 style={{ marginTop: 28 }}>最近复盘</h3>
      <table>
        <thead>
          <tr>
            <th>开奖期号</th>
            <th>策略</th>
            <th>命中号码</th>
            <th>命中数</th>
            <th>命中率</th>
          </tr>
        </thead>
        <tbody>
          {reviews.map((r) => (
            <tr key={r.id}>
              <td>{r.draw.issueNo}</td>
              <td>{r.run.strategy}</td>
              <td>{parseJsonArray(r.matchedNumbersJson).join(", ") || "-"}</td>
              <td>{r.hitCount}</td>
              <td>{(r.hitRate * 100).toFixed(2)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
