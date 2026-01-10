import apiClient from './client';
import { MusicSearchRequest, MusicSearchResponse } from '../types';

export const musicApi = {
  /**
   * Search for a song using artist and title
   */
  async searchSong(request: MusicSearchRequest): Promise<MusicSearchResponse> {
    const response = await apiClient.post<MusicSearchResponse>('/music/search', request);
    return response.data;
  },

  /**
   * Lookup a song by its streaming service URL
   */
  async lookupByUrl(url: string): Promise<MusicSearchResponse> {
    const response = await apiClient.get<MusicSearchResponse>('/music/lookup', {
      params: { url },
    });
    return response.data;
  },
};
