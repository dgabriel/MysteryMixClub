import apiClient from './client';
import { VoteCreate, VoteUpdate, UserVotesResponse } from '../types/vote';

export const votesApi = {
  cast: async (data: VoteCreate): Promise<UserVotesResponse> => {
    const response = await apiClient.post('/votes/', data);
    return response.data;
  },

  getMyVotes: async (roundId: number): Promise<UserVotesResponse | null> => {
    try {
      const response = await apiClient.get(`/votes/round/${roundId}/my-votes`);
      return response.data;
    } catch (error: any) {
      if (error.response?.status === 404) {
        return null;
      }
      throw error;
    }
  },

  update: async (roundId: number, data: VoteUpdate): Promise<UserVotesResponse> => {
    const response = await apiClient.put(`/votes/round/${roundId}`, data);
    return response.data;
  },

  delete: async (roundId: number): Promise<void> => {
    await apiClient.delete(`/votes/round/${roundId}`);
  }
};
