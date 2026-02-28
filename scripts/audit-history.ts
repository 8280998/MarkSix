import { prisma } from "../src/lib/prisma";

function parseIssue(issueNo: string): { year: string; seq: number } | null {
  const [year, seqText] = issueNo.split("/");
  const seq = Number(seqText);
  if (!year || Number.isNaN(seq)) {
    return null;
  }
  return { year, seq };
}

function checkNumbers(numbers: number[]): string[] {
  const issues: string[] = [];
  if (numbers.length !== 6) {
    issues.push("main numbers count != 6");
  }

  const seen = new Set<number>();
  for (const n of numbers) {
    if (n < 1 || n > 49) {
      issues.push(`number out of range: ${n}`);
    }
    if (seen.has(n)) {
      issues.push(`duplicate number in draw: ${n}`);
    }
    seen.add(n);
  }

  return issues;
}

async function run() {
  const draws = await prisma.draw.findMany({ orderBy: { drawDate: "asc" } });

  if (draws.length === 0) {
    console.log("No draw records found.");
    return;
  }

  const problems: string[] = [];
  const byYear = new Map<string, number[]>();
  let lastTime = 0;

  for (const d of draws) {
    const issue = parseIssue(d.issueNo);
    if (!issue) {
      problems.push(`${d.issueNo}: invalid issue format`);
      continue;
    }

    const numbers = JSON.parse(d.numbersJson) as number[];
    const numberProblems = checkNumbers(numbers);
    if (d.specialNumber < 1 || d.specialNumber > 49) {
      numberProblems.push(`special number out of range: ${d.specialNumber}`);
    }
    if (numbers.includes(d.specialNumber)) {
      numberProblems.push("special number repeated in main numbers");
    }

    if (numberProblems.length > 0) {
      problems.push(`${d.issueNo}: ${numberProblems.join("; ")}`);
    }

    const t = d.drawDate.getTime();
    if (t < lastTime) {
      problems.push(`${d.issueNo}: drawDate is not non-decreasing`);
    }
    lastTime = Math.max(lastTime, t);

    const list = byYear.get(issue.year) ?? [];
    list.push(issue.seq);
    byYear.set(issue.year, list);
  }

  for (const [year, seqList] of [...byYear.entries()].sort(([a], [b]) => a.localeCompare(b))) {
    const sorted = [...new Set(seqList)].sort((a, b) => a - b);
    const seqSet = new Set(sorted);
    const min = sorted[0];
    const max = sorted[sorted.length - 1];
    const missing: number[] = [];

    for (let i = min; i <= max; i += 1) {
      if (!seqSet.has(i)) {
        missing.push(i);
      }
    }

    if (missing.length > 0) {
      const sample = missing.slice(0, 10).join(",");
      problems.push(`${year}: missing issue seq count=${missing.length} sample=${sample}`);
    }
  }

  console.log(`Audit summary: total_draws=${draws.length}`);
  if (problems.length === 0) {
    console.log("Audit passed: no problems found.");
    return;
  }

  console.log(`Audit found ${problems.length} problem(s):`);
  for (const p of problems.slice(0, 200)) {
    console.log(`- ${p}`);
  }

  if (problems.length > 200) {
    console.log(`... truncated ${problems.length - 200} more problem(s)`);
  }

  process.exitCode = 2;
}

run()
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
