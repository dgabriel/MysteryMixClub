import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { roundsApi } from '../api';
import { RoundDetail, RoundStatus } from '../types';

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

  const copyPlaylistText = () => {
    if (!round) return;

    const playlistText = round.submissions
      .map((sub, index) => {
        const submitter = round.status === RoundStatus.COMPLETED ? ` (submitted by ${sub.user_name})` : '';
        return `${index + 1}. ${sub.song_title} - ${sub.artist_name}${submitter}`;
      })
      .join('\n');

    const fullText = `${round.theme} - Playlist\n\n${playlistText}`;
    navigator.clipboard.writeText(fullText);
    alert('Playlist copied to clipboard!');
  };

  const exportToCSV = () => {
    if (!round) return;

    const headers = ['Position', 'Song Title', 'Artist', 'Album', 'Songlink', 'Spotify', 'Apple Music', 'YouTube'];
    if (round.status === RoundStatus.COMPLETED) {
      headers.push('Submitted By');
    }

    const rows = round.submissions.map((sub, index) => {
      const row = [
        String(index + 1),
        sub.song_title,
        sub.artist_name,
        sub.album_name || '',
        sub.songlink_url,
        sub.spotify_url || '',
        sub.apple_music_url || '',
        sub.youtube_url || ''
      ];
      if (round.status === RoundStatus.COMPLETED) {
        row.push(sub.user_name || '');
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
      <div className="playlist-header">
        <div>
          <button onClick={() => navigate(`/rounds/${roundId}`)} className="btn-secondary">
            ← Back to Round
          </button>
          <h1>🎵 {round.theme}</h1>
          <p className="playlist-subtitle">
            {round.submissions.length} song{round.submissions.length !== 1 ? 's' : ''} in this playlist
          </p>
        </div>
        <div className="playlist-actions">
          <button onClick={copyPlaylistText} className="btn-secondary">
            📋 Copy Playlist
          </button>
          <button onClick={exportToCSV} className="btn-secondary">
            📥 Export CSV
          </button>
        </div>
      </div>

      <div className="playlist-list">
        {round.submissions.map((submission, index) => (
          <div key={submission.id} className="playlist-item">
            <div className="playlist-number">
              <span>{index + 1}</span>
            </div>
            <div className="playlist-info">
              <h3>{submission.song_title}</h3>
              <p className="artist">{submission.artist_name}</p>
              {submission.album_name && <p className="album">{submission.album_name}</p>}
              {round.status === RoundStatus.COMPLETED && submission.user_name && (
                <p className="submitter">Submitted by: {submission.user_name}</p>
              )}
            </div>
            <div className="playlist-links">
              {submission.songlink_url && (
                <a
                  href={submission.songlink_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="link-btn"
                >
                  🔗 Song.link
                </a>
              )}
              {submission.spotify_url && (
                <a
                  href={submission.spotify_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="link-btn spotify"
                >
                  🎵 Spotify
                </a>
              )}
              {submission.apple_music_url && (
                <a
                  href={submission.apple_music_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="link-btn apple"
                >
                  🍎 Apple Music
                </a>
              )}
              {submission.youtube_url && (
                <a
                  href={submission.youtube_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="link-btn youtube"
                >
                  ▶️ YouTube
                </a>
              )}
            </div>
          </div>
        ))}
      </div>

      {round.submissions.length === 0 && (
        <div className="empty-state">
          <p>No songs in this playlist yet.</p>
        </div>
      )}
    </div>
  );
};

export default PlaylistPage;
