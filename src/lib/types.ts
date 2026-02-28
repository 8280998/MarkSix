export type CsvDrawRecord = {
  issueNo: string;
  drawDate: Date;
  numbers: number[];
  specialNumber: number;
};

export type StrategyId = "balanced_v1" | "hot_v1" | "cold_rebound_v1" | "momentum_v1";

export type StrategyResult = {
  strategy: StrategyId;
  strategyVersion: string;
  picks: Array<{
    number: number;
    rank: number;
    score: number;
    reason: string;
  }>;
};
