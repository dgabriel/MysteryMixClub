import React, { useState } from 'react';
import { SongInput as SongInputType } from '../types';
import { musicApi } from '../api';
import StreamingLinks from './StreamingLinks';

interface SongInputProps {
  value: SongInputType;
  onChange: (song: SongInputType) => void;
  onRemove?: () => void;
  showRemove: boolean;
  order: number;
}

const SongInput: React.FC<SongInputProps> = ({ value, onChange, onRemove, showRemove, order }) => {
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSearch = async () => {
    if (!value.artist_name || !value.song_title) {
      setError('Please enter both artist and song title');
      return;
    }

    setSearching(true);
    setError(null);

    try {
      const result = await musicApi.searchSong({
        artist: value.artist_name,
        title: value.song_title,
        album: value.album_name || undefined,
      });

      // Update song with fetched data
      onChange({
        ...value,
        song_title: result.song_title || value.song_title,
        artist_name: result.artist_name || value.artist_name,
        album_name: result.album_name || value.album_name,
        songlink_url: result.songlink_url,
        spotify_url: result.spotify_url,
        apple_music_url: result.apple_music_url,
        youtube_url: result.youtube_url,
        amazon_music_url: result.amazon_music_url,
        tidal_url: result.tidal_url,
        youtube_music_url: result.youtube_music_url,
        deezer_url: result.deezer_url,
        artwork_url: result.artwork_url,
      });
    } catch (err: any) {
      const errorMsg = err.response?.data?.detail || err.message || 'Failed to find song. Please check the artist and title.';
      setError(errorMsg);
      console.error('Song search error:', err);
    } finally {
      setSearching(false);
    }
  };

  const handleFieldChange = (field: keyof SongInputType, newValue: string) => {
    onChange({
      ...value,
      [field]: newValue,
    });
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      if (value.artist_name && value.song_title && !searching) {
        handleSearch();
      }
    }
  };

  return (
    <div className="song-input">
      <div className="song-input-header">
        <h4>Song {order}</h4>
        {showRemove && onRemove && (
          <button
            type="button"
            onClick={onRemove}
            className="btn btn-danger btn-sm"
          >
            Remove
          </button>
        )}
      </div>

      {!value.songlink_url ? (
        <>
          <div className="form-group">
            <label htmlFor={`artist-${order}`}>Artist Name *</label>
            <input
              id={`artist-${order}`}
              type="text"
              className="form-control"
              placeholder="e.g., The Beatles"
              value={value.artist_name}
              onChange={(e) => handleFieldChange('artist_name', e.target.value)}
              onKeyPress={handleKeyPress}
            />
          </div>

          <div className="form-group">
            <label htmlFor={`title-${order}`}>Song Title *</label>
            <input
              id={`title-${order}`}
              type="text"
              className="form-control"
              placeholder="e.g., Hey Jude"
              value={value.song_title}
              onChange={(e) => handleFieldChange('song_title', e.target.value)}
              onKeyPress={handleKeyPress}
            />
          </div>

          <div className="form-group">
            <label htmlFor={`album-${order}`}>Album (optional)</label>
            <input
              id={`album-${order}`}
              type="text"
              className="form-control"
              placeholder="e.g., Abbey Road"
              value={value.album_name || ''}
              onChange={(e) => handleFieldChange('album_name', e.target.value)}
              onKeyPress={handleKeyPress}
            />
          </div>

          <div className="form-group">
            <button
              type="button"
              onClick={handleSearch}
              disabled={searching || !value.artist_name || !value.song_title}
              className="btn btn-primary"
            >
              {searching ? 'Searching...' : 'Find Song'}
            </button>
          </div>

          {error && (
            <div className="alert alert-danger" role="alert">
              {error}
            </div>
          )}
        </>
      ) : (
        <div className="song-preview">
          <h5>Song Found!</h5>
          {value.artwork_url && (
            <img
              src={value.artwork_url}
              alt={`${value.song_title} artwork`}
              className="song-artwork"
              style={{ maxWidth: '200px', borderRadius: '8px', marginBottom: '10px' }}
            />
          )}

          <div className="song-info" style={{ marginBottom: '15px' }}>
            <p><strong>Title:</strong> {value.song_title}</p>
            <p><strong>Artist:</strong> {value.artist_name}</p>
            {value.album_name && <p><strong>Album:</strong> {value.album_name}</p>}
          </div>

          <StreamingLinks song={value} />

          <button
            type="button"
            onClick={() => {
              // Clear the song data to allow re-entry
              onChange({
                song_title: '',
                artist_name: '',
                album_name: '',
                songlink_url: '',
                order: value.order
              });
            }}
            className="btn btn-secondary btn-sm"
            style={{ marginTop: '15px' }}
          >
            Change Song
          </button>
        </div>
      )}
    </div>
  );
};

export default SongInput;
