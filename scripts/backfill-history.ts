import { prisma } from "../src/lib/prisma";
import { filterByYearRange, loadRecordsFromPath } from "../src/lib/history-files";

type CliOptions = {
  path: string;
  fromYear?: number;
  toYear?: number;
};

function parseArgs(argv: string[]): CliOptions {
  const options: CliOptions = {
    path: process.env.HISTORY_CSV_DIR || "./data/history",
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = argv[i + 1];

    if (arg === "--path" && next) {
      options.path = next;
      i += 1;
    } else if (arg === "--from-year" && next) {
      options.fromYear = Number(next);
      i += 1;
    } else if (arg === "--to-year" && next) {
      options.toYear = Number(next);
      i += 1;
    }
  }

  if (options.fromYear && Number.isNaN(options.fromYear)) {
    throw new Error("Invalid --from-year");
  }
  if (options.toYear && Number.isNaN(options.toYear)) {
    throw new Error("Invalid --to-year");
  }

  return options;
}

async function run() {
  const options = parseArgs(process.argv.slice(2));
  const allRecords = loadRecordsFromPath(options.path);
  const records = filterByYearRange(allRecords, options.fromYear, options.toYear);

  if (records.length === 0) {
    console.log("No records matched the year range.");
    return;
  }

  let inserted = 0;
  let updated = 0;

  for (const r of records) {
    const existing = await prisma.draw.findUnique({
      where: { issueNo: r.issueNo },
      select: { id: true },
    });

    if (existing) {
      await prisma.draw.update({
        where: { issueNo: r.issueNo },
        data: {
          drawDate: r.drawDate,
          numbersJson: JSON.stringify(r.numbers),
          specialNumber: r.specialNumber,
          source: "backfill_csv",
        },
      });
      updated += 1;
      continue;
    }

    await prisma.draw.create({
      data: {
        issueNo: r.issueNo,
        drawDate: r.drawDate,
        numbersJson: JSON.stringify(r.numbers),
        specialNumber: r.specialNumber,
        source: "backfill_csv",
      },
    });
    inserted += 1;
  }

  console.log(
    `Backfill complete: total=${records.length}, inserted=${inserted}, updated=${updated}, path=${options.path}`,
  );
}

run()
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
