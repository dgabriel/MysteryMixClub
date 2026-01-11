import React from 'react';
import StreamingLinks from './StreamingLinks';
import { Song } from '../types';

export interface TrackCardProps {
  // Core song data
  song: {
    id?: number;
    song_title: string;
    artist_name: string;
    album_name?: string | null;
    artwork_url?: string | null;
    songlink_url?: string | null;
    spotify_url?: string | null;
    apple_music_url?: string | null;
    youtube_url?: string | null;
    amazon_music_url?: string | null;
    tidal_url?: string | null;
    youtube_music_url?: string | null;
    deezer_url?: string | null;
  };

  // Display options
  showArtwork?: boolean;
  showAlbum?: boolean;
  showStreamingLinks?: boolean;

  // Position/rank display
  position?: number;
  rankBadge?: number; // Small rank badge overlay

  // Submitter info
  submitterName?: string | null;
  showSubmitter?: boolean;

  // Styling variants
  variant?: 'default' | 'compact' | 'playlist';
  highlighted?: boolean;

  // Interactive props
  onClick?: () => void;
  className?: string;

  // Children for custom content (e.g., vote controls)
  children?: React.ReactNode;
}

const TrackCard: React.FC<TrackCardProps> = ({
  song,
  showArtwork = true,
  showAlbum = true,
  showStreamingLinks = true,
  position,
  rankBadge,
  submitterName,
  showSubmitter = false,
  variant = 'default',
  highlighted = false,
  onClick,
  className = '',
  children,
}) => {
  const baseClass = variant === 'playlist' ? 'playlist-item' : 'submission-card';
  const highlightClass = highlighted ? 'my-submission' : '';
  const clickableClass = onClick ? 'clickable' : '';

  const artworkClass = variant === 'playlist' ? 'playlist-artwork' : 'song-artwork';
  const infoClass = variant === 'playlist' ? 'playlist-info' : 'submission-info';
  const titleTag = variant === 'playlist' ? 'h3' : 'h4';

  return (
    <div
      className={`${baseClass} ${highlightClass} ${clickableClass} ${className}`.trim()}
      onClick={onClick}
    >
      {/* Position number (for playlists) */}
      {position !== undefined && (
        <div className="playlist-number">
          <span>{position}</span>
        </div>
      )}

      {/* Rank badge overlay (for voting) */}
      {rankBadge !== undefined && (
        <span className="rank-badge-small">{rankBadge}</span>
      )}

      {/* Album artwork */}
      {showArtwork && song.artwork_url && (
        <img
          src={song.artwork_url}
          alt={`${song.song_title} artwork`}
          className={artworkClass}
        />
      )}

      {/* Song info */}
      <div className={infoClass}>
        {titleTag === 'h3' ? (
          <h3>{song.song_title}</h3>
        ) : (
          <h4>{song.song_title}</h4>
        )}
        <p className={variant === 'playlist' ? 'artist' : ''}>{song.artist_name}</p>
        {showAlbum && song.album_name && (
          <p className={variant === 'playlist' ? 'album' : 'album-name'}>{song.album_name}</p>
        )}
        {showSubmitter && submitterName && (
          <p className="submitter">Submitted by: {submitterName}</p>
        )}
      </div>

      {/* Streaming links */}
      {showStreamingLinks && (
        <div onClick={(e) => e.stopPropagation()}>
          <StreamingLinks song={song as Song} />
        </div>
      )}

      {/* Custom children (for vote controls, etc.) */}
      {children}
    </div>
  );
};

export default TrackCard;
