import apiClient from './client';
import { Round, RoundDetail, RoundCreate, RoundUpdate, RoundReorderItem, Submission, SubmissionCreate } from '../types/round';
import { RoundResults } from '../types/results';

export const roundsApi = {
  // Round endpoints
  create: async (data: RoundCreate): Promise<Round> => {
    const response = await apiClient.post('/rounds/', data);
    return response.data;
  },

  getLeagueRounds: async (leagueId: number): Promise<Round[]> => {
    const response = await apiClient.get(`/rounds/league/${leagueId}`);
    return response.data;
  },

  getById: async (roundId: number): Promise<RoundDetail> => {
    const response = await apiClient.get(`/rounds/${roundId}`);
    return response.data;
  },

  update: async (roundId: number, data: RoundUpdate): Promise<Round> => {
    const response = await apiClient.put(`/rounds/${roundId}`, data);
    return response.data;
  },

  delete: async (roundId: number): Promise<void> => {
    await apiClient.delete(`/rounds/${roundId}`);
  },

  start: async (roundId: number): Promise<Round> => {
    const response = await apiClient.post(`/rounds/${roundId}/start`);
    return response.data;
  },

  complete: async (roundId: number): Promise<Round> => {
    const response = await apiClient.post(`/rounds/${roundId}/complete`);
    return response.data;
  },

  reorder: async (leagueId: number, rounds: RoundReorderItem[]): Promise<Round[]> => {
    const response = await apiClient.post(`/rounds/league/${leagueId}/reorder`, rounds);
    return response.data;
  },

  getResults: async (roundId: number): Promise<RoundResults> => {
    const response = await apiClient.get(`/rounds/${roundId}/results`);
    return response.data;
  },

  // Submission endpoints
  submitSong: async (data: SubmissionCreate): Promise<Submission> => {
    const response = await apiClient.post('/submissions/', data);
    return response.data;
  },

  getMySubmission: async (roundId: number): Promise<Submission> => {
    const response = await apiClient.get(`/submissions/round/${roundId}/my-submission`);
    return response.data;
  },

  deleteSubmission: async (submissionId: number): Promise<void> => {
    await apiClient.delete(`/submissions/${submissionId}`);
  }
};
