import apiClient from './client';
import {
  League,
  LeagueDetail,
  LeagueCreate,
  LeagueUpdate,
  JoinLeagueRequest
} from '../types';
import { LeagueLeaderboard } from '../types/leaderboard';

export const leaguesApi = {
  /**
   * Create a new league
   */
  create: async (data: LeagueCreate): Promise<League> => {
    const response = await apiClient.post<League>('/leagues/', data);
    return response.data;
  },

  /**
   * Get all leagues the user is a member of
   */
  getMyLeagues: async (): Promise<League[]> => {
    const response = await apiClient.get<League[]>('/leagues/');
    return response.data;
  },

  /**
   * Get league details with members
   */
  getLeague: async (leagueId: number): Promise<LeagueDetail> => {
    const response = await apiClient.get<LeagueDetail>(`/leagues/${leagueId}`);
    return response.data;
  },

  /**
   * Join a league using invite code
   */
  join: async (data: JoinLeagueRequest): Promise<League> => {
    const response = await apiClient.post<League>('/leagues/join', data);
    return response.data;
  },

  /**
   * Leave a league
   */
  leave: async (leagueId: number): Promise<void> => {
    await apiClient.post(`/leagues/${leagueId}/leave`);
  },

  /**
   * Update league (admin only)
   */
  update: async (leagueId: number, data: LeagueUpdate): Promise<League> => {
    const response = await apiClient.put<League>(`/leagues/${leagueId}`, data);
    return response.data;
  },

  /**
   * Delete league (creator only)
   */
  delete: async (leagueId: number): Promise<void> => {
    await apiClient.delete(`/leagues/${leagueId}`);
  },

  /**
   * Get league leaderboard with cumulative points
   */
  getLeaderboard: async (leagueId: number): Promise<LeagueLeaderboard> => {
    const response = await apiClient.get<LeagueLeaderboard>(`/leagues/${leagueId}/leaderboard`);
    return response.data;
  },
};
