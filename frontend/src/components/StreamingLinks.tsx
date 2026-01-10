import React, { useState } from 'react';
import { Song, SongInput } from '../types';

interface StreamingLinksProps {
  song: Song | SongInput;
}

interface StreamingService {
  name: string;
  url?: string;
  icon?: string;
}

const StreamingLinks: React.FC<StreamingLinksProps> = ({ song }) => {
  const [expanded, setExpanded] = useState(false);

  const services: StreamingService[] = [
    { name: 'Spotify', url: song.spotify_url },
    { name: 'Apple Music', url: song.apple_music_url },
    { name: 'YouTube', url: song.youtube_url },
    { name: 'Amazon Music', url: song.amazon_music_url },
    { name: 'Tidal', url: song.tidal_url },
    { name: 'YouTube Music', url: song.youtube_music_url },
    { name: 'Deezer', url: song.deezer_url },
  ].filter(service => service.url);

  if (!song.songlink_url && services.length === 0) {
    return null;
  }

  return (
    <div className="streaming-links">
      {song.songlink_url && (
        <div className="universal-link">
          <a
            href={song.songlink_url}
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-primary btn-sm"
          >
            🔗 Open in Your Preferred Service
          </a>
        </div>
      )}

      {services.length > 0 && (
        <div className="service-links">
          <button
            onClick={() => setExpanded(!expanded)}
            className="btn btn-link btn-sm"
            type="button"
          >
            {expanded ? '▼' : '▶'} {services.length} Streaming Service{services.length !== 1 ? 's' : ''}
          </button>

          {expanded && (
            <div className="service-list">
              {services.map(service => (
                <a
                  key={service.name}
                  href={service.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="service-link"
                >
                  {service.name}
                </a>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default StreamingLinks;
