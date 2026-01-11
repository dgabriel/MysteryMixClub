import React, { useState, useEffect, useMemo } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { roundsApi } from '../api';
import { RoundDetail, RoundStatus, Song } from '../types';
import TrackCard from '../components/TrackCard';

// Extract YouTube video ID from various URL formats
function extractYouTubeVideoId(url: string): string | null {
  const patterns = [
    /(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})/,
    /^([a-zA-Z0-9_-]{11})$/ // Just the ID itself
  ];

  for (const pattern of patterns) {
    const match = url.match(pattern);
    if (match) return match[1];
  }
  return null;
}

// Generate YouTube playlist URL from video IDs with optional title
function generateYouTubePlaylistUrl(videoIds: string[], title?: string): string {
  const baseUrl = `https://www.youtube.com/watch_videos?video_ids=${videoIds.join(',')}`;
  return title ? `${baseUrl}&title=${encodeURIComponent(title)}` : baseUrl;
}

// Fisher-Yates shuffle with seed for consistent randomization per round
function seededShuffle<T>(array: T[], seed: number): T[] {
  const shuffled = [...array];
  let currentIndex = shuffled.length;

  // Simple seeded random number generator
  const seededRandom = () => {
    seed = (seed * 1103515245 + 12345) & 0x7fffffff;
    return seed / 0x7fffffff;
  };

  while (currentIndex > 0) {
    const randomIndex = Math.floor(seededRandom() * currentIndex);
    currentIndex--;
    [shuffled[currentIndex], shuffled[randomIndex]] = [shuffled[randomIndex], shuffled[currentIndex]];
  }

  return shuffled;
}

interface PlaylistSong extends Song {
  user_name?: string | null;
}

const PlaylistPage: React.FC = () => {
  const { roundId } = useParams<{ roundId: string }>();
  const navigate = useNavigate();
  const [round, setRound] = useState<RoundDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (roundId) {
      loadRound();
    }
  }, [roundId]);

  const loadRound = async () => {
    try {
      setLoading(true);
      const data = await roundsApi.getById(Number(roundId));
      setRound(data);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load round');
    } finally {
      setLoading(false);
    }
  };

  // Flatten all songs from submissions and shuffle them
  const shuffledSongs = useMemo(() => {
    if (!round) return [];

    // Flatten songs from all submissions, attaching user_name to each song
    const allSongs: PlaylistSong[] = [];
    for (const submission of round.submissions) {
      for (const song of submission.songs) {
        allSongs.push({
          ...song,
          user_name: submission.user_name
        });
      }
    }

    // Use round ID as seed for consistent shuffle per round
    return seededShuffle(allSongs, round.id);
  }, [round]);

  // Determine if we should show submitter names
  const showSubmitters = round?.status === RoundStatus.COMPLETED || round?.user_has_voted;

  // Generate YouTube playlist URL from songs that have YouTube links
  const youtubePlaylistUrl = useMemo(() => {
    if (!round) return null;

    const videoIds = shuffledSongs
      .map(song => song.youtube_url ? extractYouTubeVideoId(song.youtube_url) : null)
      .filter((id): id is string => id !== null);

    if (videoIds.length === 0) return null;

    const playlistTitle = round.league_name
      ? `${round.league_name}: ${round.theme}`
      : round.theme;

    return generateYouTubePlaylistUrl(videoIds, playlistTitle);
  }, [shuffledSongs, round]);

  const copyPlaylistText = () => {
    if (!round) return;

    const playlistText = shuffledSongs
      .map((song, index) => {
        const submitter = showSubmitters && song.user_name ? ` (submitted by ${song.user_name})` : '';
        return `${index + 1}. ${song.song_title} - ${song.artist_name}${submitter}`;
      })
      .join('\n');

    const fullText = `${round.theme} - Playlist\n\n${playlistText}`;
    navigator.clipboard.writeText(fullText);
    alert('Playlist copied to clipboard!');
  };

  const copySpotifyLinks = () => {
    const spotifyUrls = shuffledSongs
      .map(song => song.spotify_url)
      .filter((url): url is string => url !== null && url !== undefined);

    if (spotifyUrls.length === 0) {
      alert('No Spotify links available for this playlist.');
      return;
    }

    navigator.clipboard.writeText(spotifyUrls.join('\n'));
    alert(`${spotifyUrls.length} Spotify link${spotifyUrls.length !== 1 ? 's' : ''} copied! Paste into a Spotify playlist.`);
  };

  const exportToCSV = () => {
    if (!round) return;

    const headers = ['Position', 'Song Title', 'Artist', 'Album', 'Songlink', 'Spotify', 'Apple Music', 'YouTube'];
    if (showSubmitters) {
      headers.push('Submitted By');
    }

    const rows = shuffledSongs.map((song, index) => {
      const row = [
        String(index + 1),
        song.song_title,
        song.artist_name,
        song.album_name || '',
        song.songlink_url || '',
        song.spotify_url || '',
        song.apple_music_url || '',
        song.youtube_url || ''
      ];
      if (showSubmitters) {
        row.push(song.user_name || '');
      }
      return row;
    });

    const csvContent = [
      headers.join(','),
      ...rows.map(row => row.map(cell => `"${cell}"`).join(','))
    ].join('\n');

    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${round.theme.replace(/[^a-z0-9]/gi, '_').toLowerCase()}_playlist.csv`;
    a.click();
    window.URL.revokeObjectURL(url);
  };

  if (loading) {
    return <div className="loading">Loading playlist...</div>;
  }

  if (error || !round) {
    return (
      <div className="error-container">
        <h2>Error</h2>
        <p>{error || 'Round not found'}</p>
        <button onClick={() => navigate(-1)} className="btn-primary">
          Go Back
        </button>
      </div>
    );
  }

  return (
    <div className="playlist-container">
      {round.league_name && (
        <Link to={`/leagues/${round.league_id}`} className="league-banner">
          {round.league_name}
        </Link>
      )}
      <div className="playlist-header">
        <div>
          <button onClick={() => navigate(`/rounds/${roundId}`)} className="btn-secondary">
            ← Back to Round
          </button>
          <h1>{round.theme}</h1>
          <p className="playlist-subtitle">
            {shuffledSongs.length} song{shuffledSongs.length !== 1 ? 's' : ''} in this playlist
            {!showSubmitters && ' • Vote to reveal who submitted each song'}
          </p>
        </div>
        <div className="playlist-actions">
          {youtubePlaylistUrl && (
            <a
              href={youtubePlaylistUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-primary"
            >
              ▶ Play All on YouTube
            </a>
          )}
          <button onClick={copySpotifyLinks} className="btn-primary">
            Copy for Spotify
          </button>
          <button onClick={copyPlaylistText} className="btn-secondary">
            Copy Playlist
          </button>
          <button onClick={exportToCSV} className="btn-secondary">
            Export CSV
          </button>
        </div>
      </div>

      <div className="playlist-list">
        {shuffledSongs.map((song, index) => (
          <TrackCard
            key={song.id}
            song={song}
            variant="playlist"
            position={index + 1}
            submitterName={song.user_name}
            showSubmitter={showSubmitters}
          />
        ))}
      </div>

      {shuffledSongs.length === 0 && (
        <div className="empty-state">
          <p>No songs in this playlist yet.</p>
        </div>
      )}
    </div>
  );
};

export default PlaylistPage;
