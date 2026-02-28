import { prisma } from "../src/lib/prisma";
import { loadDrawRecords } from "../src/lib/data-source";
import { generatePredictionsForNextIssue } from "../src/lib/prediction-service";

const BOOTSTRAP_FLAG = "history_bootstrap_completed";

function hasForceFlag(): boolean {
  return process.argv.slice(2).includes("--force");
}

async function run() {
  const force = hasForceFlag();
  const flag = await prisma.systemState.findUnique({ where: { key: BOOTSTRAP_FLAG } });

  if (flag?.value === "true" && !force) {
    console.log("History bootstrap already completed. Skip.");
    return;
  }

  const records = await loadDrawRecords();
  let inserted = 0;

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
      select: { createdAt: true, updatedAt: true },
    });

    if (created.createdAt.getTime() === created.updatedAt.getTime()) {
      inserted += 1;
    }
  }

  await prisma.systemState.upsert({
    where: { key: BOOTSTRAP_FLAG },
    update: { value: "true" },
    create: { key: BOOTSTRAP_FLAG, value: "true" },
  });

  const issueNo = await generatePredictionsForNextIssue();
  console.log(`Bootstrap done. inserted=${inserted}, force=${force}, generated_predictions_for=${issueNo}`);
}

run()
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
