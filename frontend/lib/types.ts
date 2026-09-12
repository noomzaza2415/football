// Mirrors the Pydantic schemas in backend/app/schemas.py.

export type MatchStatus = "scheduled" | "finished" | "postponed" | "cancelled";

export interface Team {
  id: number;
  name: string;
  short_name: string | null;
  league: string;
  country: string | null;
  crest_url: string | null;
}

export interface TeamStats {
  team_id: number;
  matches_played: number;
  matches_played_home: number;
  matches_played_away: number;
  avg_goals_scored_home: number;
  avg_goals_scored_away: number;
  avg_goals_conceded_home: number;
  avg_goals_conceded_away: number;
  avg_total_goals: number;
  over_2_5_rate: number;
  btts_rate: number;
  form_last_5: string;
  form_points_last_5: number;
  attack_strength_home: number;
  attack_strength_away: number;
  defense_strength_home: number;
  defense_strength_away: number;
  sample_matches: number;
  updated_at: string | null;
}

export interface TeamWithStats {
  team: Team;
  stats: TeamStats | null;
}

export interface Match {
  id: number;
  league: string;
  season: string | null;
  match_date: string;
  status: MatchStatus;
  home_team: Team;
  away_team: Team;
  home_goals: number | null;
  away_goals: number | null;
  market_line: number | null;
  market_odds_over: number | null;
  market_odds_under: number | null;
}

export type Lean = "OVER" | "UNDER" | "NEUTRAL";

export interface MatchSummary {
  match: Match;
  expected_total_goals: number | null;
  prob_over_2_5: number | null;
  prob_under_2_5: number | null;
  lean: Lean | null;
  edge_over_2_5: number | null;
  model_version: string | null;
}

export interface LineProbability {
  line: number;
  prob_over: number;
  prob_under: number;
  prob_push: number;
  fair_odds_over: number | null;
  fair_odds_under: number | null;
}

export interface TotalGoalsBucket {
  total_goals: number;
  probability: number;
}

export interface Scoreline {
  home_goals: number;
  away_goals: number;
  probability: number;
}

export interface MarketComparison {
  line: number;
  selection: "OVER" | "UNDER";
  decimal_odds: number;
  market_probability: number;
  fair_market_probability: number;
  model_probability: number;
  edge: number;
  expected_value: number;
  is_value: boolean;
  kelly_fraction: number;
}

export interface Prediction {
  match: Match;
  expected_home_goals: number;
  expected_away_goals: number;
  expected_total_goals: number;
  prob_home_win: number;
  prob_draw: number;
  prob_away_win: number;
  most_likely_score: string;
  lines: LineProbability[];
  total_goals_distribution: TotalGoalsBucket[];
  top_scorelines: Scoreline[];
  market_comparison: MarketComparison[];
  sample_matches: number;
  model_version: string;
  created_at: string | null;
  disclaimer: string;
}

export interface PredictionHistoryItem {
  match_id: number;
  match_date: string;
  league: string;
  home_team: string;
  away_team: string;
  predicted_total_goals: number;
  prob_over_2_5: number;
  model_pick: Lean;
  actual_home_goals: number;
  actual_away_goals: number;
  actual_total_goals: number;
  actual_result: "OVER" | "UNDER";
  correct: boolean;
  model_version: string;
  created_at: string | null;
}

export interface CalibrationBucket {
  bucket: string;
  predicted_probability: number;
  actual_rate: number;
  samples: number;
}

export interface PredictionHistory {
  items: PredictionHistoryItem[];
  total: number;
  evaluated: number;
  correct: number;
  accuracy: number;
  over_picks: number;
  under_picks: number;
  over_hit_rate: number;
  under_hit_rate: number;
  brier_score: number;
  mean_absolute_goal_error: number;
  calibration: CalibrationBucket[];
  disclaimer: string;
}

export interface ScoreCard {
  name: string;
  brier: number;
  log_loss: number;
  samples: number;
  skill_vs_base_rate: number | null;
}

export interface BacktestRecord {
  match_id: number;
  kickoff: string;
  league: string;
  home_team: string;
  away_team: string;
  train_size: number;
  predicted_total_goals: number;
  prob_over: number;
  model_pick: Lean;
  actual_home_goals: number;
  actual_away_goals: number;
  actual_total_goals: number;
  actual_result: "OVER" | "UNDER";
  correct: boolean | null;
  profit: number | null;
}

export interface Backtest {
  model_version: string;
  line: number;
  window: "expanding" | "rolling";
  train_window: number | null;
  min_train_matches: number;
  last_n: number;
  rho: number;
  tested: number;
  scored: number;
  accuracy: number;
  actual_over_rate: number;
  mean_absolute_goal_error: number;
  rmse_goals: number;
  scorecards: ScoreCard[];
  calibration: CalibrationBucket[];
  priced_picks: number;
  profit: number;
  roi: number;
  records: BacktestRecord[];
  disclaimer: string;
}

export interface Health {
  status: string;
  environment: string;
  model_version: string;
  teams: number;
  matches: number;
  finished_matches: number;
  predictions: number;
}
