export interface Song {
  id: number;
  submission_id: number;
  song_title: string;
  artist_name: string;
  album_name?: string;
  songlink_url: string;
  spotify_url?: string;
  apple_music_url?: string;
  youtube_url?: string;
  amazon_music_url?: string;
  tidal_url?: string;
  youtube_music_url?: string;
  deezer_url?: string;
  artwork_url?: string;
  order: number;
  created_at: string;
  vote_count?: number;
  average_rank?: number;
}

export interface SongInput {
  song_title: string;
  artist_name: string;
  album_name?: string;
  songlink_url: string;
  spotify_url?: string;
  apple_music_url?: string;
  youtube_url?: string;
  amazon_music_url?: string;
  tidal_url?: string;
  youtube_music_url?: string;
  deezer_url?: string;
  artwork_url?: string;
  order: number;
}

export interface MusicSearchRequest {
  artist: string;
  title: string;
  album?: string;
}

export interface MusicSearchResponse {
  songlink_url: string;
  song_title?: string;
  artist_name?: string;
  album_name?: string;
  artwork_url?: string;
  spotify_url?: string;
  apple_music_url?: string;
  youtube_url?: string;
  amazon_music_url?: string;
  tidal_url?: string;
  youtube_music_url?: string;
  deezer_url?: string;
}

export function createEmptySongInput(order: number = 1): SongInput {
  return {
    song_title: '',
    artist_name: '',
    album_name: '',
    songlink_url: '',
    order,
  };
}
