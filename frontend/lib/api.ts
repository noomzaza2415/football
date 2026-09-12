// Thin typed wrapper over the FastAPI backend.
//
// Every call is made from a React Server Component with caching disabled,
// because fixtures and prices move and a stale card is worse than a slow one.

import type {
  Backtest,
  Health,
  Match,
  MatchSummary,
  Prediction,
  PredictionHistory,
  Team,
  TeamWithStats,
} from "./types";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${API_BASE_URL}${path}`;

  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      cache: "no-store",
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch (cause) {
    throw new ApiError(
      `Cannot reach the analytics API at ${url}. Is the backend running?`,
      0,
    );
  }

  if (!response.ok) {
    const body = await response.text();
    throw new ApiError(
      `${init?.method ?? "GET"} ${path} failed with ${response.status}: ${body.slice(0, 200)}`,
      response.status,
    );
  }

  return (await response.json()) as T;
}

/** Returns null instead of throwing, for pages that render an empty state. */
export async function tryRequest<T>(promise: Promise<T>): Promise<T | null> {
  try {
    return await promise;
  } catch (error) {
    if (error instanceof ApiError) {
      console.error(error.message);
      return null;
    }
    throw error;
  }
}

export const api = {
  health: () => request<Health>("/health"),

  teams: (league?: string) =>
    request<Team[]>(`/teams${league ? `?league=${encodeURIComponent(league)}` : ""}`),

  teamStats: (teamId: number) => request<TeamWithStats>(`/teams/${teamId}/stats`),

  upcomingMatches: (days = 14, limit = 50) =>
    request<MatchSummary[]>(`/matches/upcoming?days=${days}&limit=${limit}`),

  match: (matchId: number) => request<Match>(`/matches/${matchId}`),

  prediction: (matchId: number) => request<Prediction>(`/matches/${matchId}/prediction`),

  refreshPrediction: (matchId: number) =>
    request<Prediction>(`/matches/${matchId}/refresh-prediction`, {
      method: "POST",
      body: JSON.stringify({}),
    }),

  predictionHistory: (limit = 200) =>
    request<PredictionHistory>(`/predictions/history?limit=${limit}`),

  backtest: (minTrainMatches = 60) =>
    request<Backtest>(`/predictions/backtest?min_train_matches=${minTrainMatches}`),
};
