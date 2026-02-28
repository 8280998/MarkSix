import { prisma } from "../src/lib/prisma";
import { generatePredictionsForNextIssue } from "../src/lib/prediction-service";

async function run() {
  const issueNo = await generatePredictionsForNextIssue();
  console.log(`Generated predictions for ${issueNo}`);
}

run()
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
