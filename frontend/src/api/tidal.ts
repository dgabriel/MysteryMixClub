import client from './client';

export interface TidalAuthStartResponse {
  auth_url: string;
  device_code: string;
  user_code: string;
  expires_in: number;
  interval: number;
}

export interface TidalAuthCompleteResponse {
  success: boolean;
  message: string;
}

export interface TidalStatusResponse {
  connected: boolean;
  user_id: string | null;
}

export interface CreatePlaylistRequest {
  name: string;
  description?: string;
  tidal_urls: string[];
}

export interface CreatePlaylistResponse {
  success: boolean;
  playlist_id: string;
  playlist_url: string;
  track_count: number;
  skipped_count: number;
}

export const tidalApi = {
  /**
   * Get current Tidal connection status
   */
  getStatus: async (): Promise<TidalStatusResponse> => {
    const response = await client.get('/tidal/status');
    return response.data;
  },

  /**
   * Start Tidal device authorization flow
   */
  startAuth: async (): Promise<TidalAuthStartResponse> => {
    const response = await client.get('/tidal/auth-start');
    return response.data;
  },

  /**
   * Check if authorization is complete and save session
   */
  completeAuth: async (deviceCode: string): Promise<TidalAuthCompleteResponse> => {
    const response = await client.post('/tidal/auth-complete', {
      device_code: deviceCode,
    });
    return response.data;
  },

  /**
   * Disconnect Tidal account
   */
  disconnect: async (): Promise<void> => {
    await client.delete('/tidal/disconnect');
  },

  /**
   * Create a playlist in the user's Tidal account
   */
  createPlaylist: async (data: CreatePlaylistRequest): Promise<CreatePlaylistResponse> => {
    const response = await client.post('/tidal/playlist', data);
    return response.data;
  },
};
