import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { roundsApi, votesApi } from '../api';
import { RoundDetail, Submission, RoundStatus } from '../types';
import { UserVotesResponse } from '../types/vote';
import { RoundResults } from '../types/results';

const RoundDetailPage: React.FC = () => {
  const { roundId } = useParams<{ roundId: string }>();
  const navigate = useNavigate();
  const [round, setRound] = useState<RoundDetail | null>(null);
  const [mySubmission, setMySubmission] = useState<Submission | null>(null);
  const [myVotes, setMyVotes] = useState<UserVotesResponse | null>(null);
  const [rankedSubmissions, setRankedSubmissions] = useState<number[]>([]);
  const [results, setResults] = useState<RoundResults | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showSubmitModal, setShowSubmitModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [showEditRoundModal, setShowEditRoundModal] = useState(false);

  useEffect(() => {
    if (roundId) {
      loadRound();
      loadMySubmission();
      loadMyVotes();
      loadResults();
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

  const loadMySubmission = async () => {
    try {
      const data = await roundsApi.getMySubmission(Number(roundId));
      setMySubmission(data);
    } catch (err: any) {
      // No submission yet - that's ok
      setMySubmission(null);
    }
  };

  const handleSubmitSong = async (
    songTitle: string,
    artistName: string,
    albumName: string,
    songlink: string,
    spotify: string,
    appleMusic: string,
    youtube: string,
    artwork: string
  ) => {
    try {
      await roundsApi.submitSong({
        round_id: Number(roundId),
        song_title: songTitle,
        artist_name: artistName,
        album_name: albumName || undefined,
        songlink_url: songlink,
        spotify_url: spotify || undefined,
        apple_music_url: appleMusic || undefined,
        youtube_url: youtube || undefined,
        artwork_url: artwork || undefined
      });
      setShowSubmitModal(false);
      loadRound();
      loadMySubmission();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to submit song');
    }
  };

  const handleEditSubmission = async (
    songTitle: string,
    artistName: string,
    albumName: string,
    songlink: string,
    spotify: string,
    appleMusic: string,
    youtube: string,
    artwork: string
  ) => {
    if (!mySubmission) return;

    try {
      await roundsApi.updateSubmission(mySubmission.id, {
        song_title: songTitle,
        artist_name: artistName,
        album_name: albumName || undefined,
        songlink_url: songlink,
        spotify_url: spotify || undefined,
        apple_music_url: appleMusic || undefined,
        youtube_url: youtube || undefined,
        artwork_url: artwork || undefined
      });
      setShowEditModal(false);
      loadRound();
      loadMySubmission();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to update submission');
    }
  };

  const handleDeleteSubmission = async () => {
    if (!mySubmission) return;

    if (!window.confirm('Are you sure you want to delete your submission?')) {
      return;
    }

    try {
      await roundsApi.deleteSubmission(mySubmission.id);
      loadRound();
      loadMySubmission();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to delete submission');
    }
  };

  const loadMyVotes = async () => {
    try {
      const data = await votesApi.getMyVotes(Number(roundId));
      setMyVotes(data);
      if (data) {
        setRankedSubmissions(data.ranked_submissions);
      }
    } catch (err: any) {
      // No votes yet - that's ok
      setMyVotes(null);
      setRankedSubmissions([]);
    }
  };

  const loadResults = async () => {
    try {
      const data = await roundsApi.getResults(Number(roundId));
      setResults(data);
    } catch (err: any) {
      // Results not available yet - that's ok
      setResults(null);
    }
  };

  const handleCastVotes = async () => {
    if (rankedSubmissions.length === 0) {
      setError('Please select at least one submission to vote for');
      return;
    }

    try {
      await votesApi.cast({
        round_id: Number(roundId),
        ranked_submissions: rankedSubmissions
      });
      loadMyVotes();
      loadRound();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to cast votes');
    }
  };

  const handleToggleVote = (submissionId: number) => {
    setRankedSubmissions(prev => {
      if (prev.includes(submissionId)) {
        // Remove from ranking
        return prev.filter(id => id !== submissionId);
      } else if (prev.length < 3) {
        // Add to ranking (max 3)
        return [...prev, submissionId];
      } else {
        // Replace last one
        return [...prev.slice(0, 2), submissionId];
      }
    });
  };

  const handleMoveUp = (submissionId: number) => {
    setRankedSubmissions(prev => {
      const index = prev.indexOf(submissionId);
      if (index <= 0) return prev;
      const newRanking = [...prev];
      [newRanking[index - 1], newRanking[index]] = [newRanking[index], newRanking[index - 1]];
      return newRanking;
    });
  };

  const handleMoveDown = (submissionId: number) => {
    setRankedSubmissions(prev => {
      const index = prev.indexOf(submissionId);
      if (index < 0 || index >= prev.length - 1) return prev;
      const newRanking = [...prev];
      [newRanking[index], newRanking[index + 1]] = [newRanking[index + 1], newRanking[index]];
      return newRanking;
    });
  };

  const getStatusBadgeClass = (status: string) => {
    const badges: Record<string, string> = {
      pending: 'status-pending',
      active: 'status-active',
      completed: 'status-completed'
    };
    return badges[status] || '';
  };

  const canSubmit = () => {
    if (!round) return false;
    // Can submit if round is ACTIVE and voting hasn't started yet
    return round.status === RoundStatus.ACTIVE && !round.voting_started_at && !mySubmission;
  };

  const canEdit = () => {
    if (!round || !mySubmission) return false;
    // Can edit during submission phase (before voting starts)
    return round.status === RoundStatus.ACTIVE && !round.voting_started_at;
  };

  const canVote = () => {
    if (!round) return false;
    // Can vote if round is ACTIVE and voting has started
    return round.status === RoundStatus.ACTIVE && round.voting_started_at !== null;
  };

  const canEditRound = () => {
    if (!round || !round.is_admin) return false;
    // Can only edit PENDING rounds
    return round.status === RoundStatus.PENDING;
  };

  const canStartRound = () => {
    if (!round || !round.is_admin) return false;
    return round.status === RoundStatus.PENDING;
  };

  const canCompleteRound = () => {
    if (!round || !round.is_admin) return false;
    return round.status === RoundStatus.ACTIVE;
  };

  const handleEditRound = async (theme: string, description: string) => {
    try {
      await roundsApi.update(Number(roundId), {
        theme,
        description
      });
      setShowEditRoundModal(false);
      loadRound();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to update round');
    }
  };

  const handleDeleteRound = async () => {
    if (!window.confirm('Are you sure you want to delete this round? This cannot be undone!')) {
      return;
    }

    try {
      await roundsApi.delete(Number(roundId));
      navigate(-1); // Go back to previous page
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to delete round');
    }
  };

  const handleStartRound = async () => {
    if (!window.confirm('Start this round? This will set deadlines automatically (2 days for submission, 5 days for voting).')) {
      return;
    }

    try {
      await roundsApi.start(Number(roundId));
      loadRound();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to start round');
    }
  };

  const handleCompleteRound = async () => {
    if (!window.confirm('Complete this round early? This will auto-start the next pending round if one exists.')) {
      return;
    }

    try {
      await roundsApi.complete(Number(roundId));
      loadRound();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to complete round');
    }
  };

  if (loading) {
    return <div className="loading">Loading round...</div>;
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

  const submissionDeadlinePassed = round.submission_deadline ? new Date(round.submission_deadline) < new Date() : false;
  const votingDeadlinePassed = round.voting_deadline ? new Date(round.voting_deadline) < new Date() : false;

  return (
    <div className="round-detail-container">
      <div className="round-detail-header">
        <div>
          <h1>{round.theme}</h1>
          {round.description && <p className="round-description">{round.description}</p>}
        </div>
        <div className="round-actions">
          <span className={`status-badge ${getStatusBadgeClass(round.status)}`}>
            {round.status.toUpperCase()}
          </span>
          {round.submissions.length > 0 && (
            <button
              onClick={() => navigate(`/rounds/${roundId}/playlist`)}
              className="btn-secondary"
            >
              🎵 View Playlist
            </button>
          )}
          {round.is_admin && (
            <div className="round-admin-actions">
              {canStartRound() && (
                <button onClick={handleStartRound} className="btn-primary">
                  Start Round
                </button>
              )}
              {canCompleteRound() && (
                <button onClick={handleCompleteRound} className="btn-primary">
                  Complete Round
                </button>
              )}
              {canEditRound() && (
                <>
                  <button onClick={() => setShowEditRoundModal(true)} className="btn-secondary">
                    Edit Round
                  </button>
                  <button onClick={handleDeleteRound} className="btn-danger">
                    Delete Round
                  </button>
                </>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="round-info-section">
        {round.submission_deadline && (
          <div className="deadline-card">
            <h4>Submission Deadline</h4>
            <p className={submissionDeadlinePassed ? 'deadline-passed' : ''}>
              {new Date(round.submission_deadline).toLocaleString()}
            </p>
            {submissionDeadlinePassed && <span className="deadline-status">Closed</span>}
          </div>
        )}
        {round.voting_deadline && (
          <div className="deadline-card">
            <h4>Voting Deadline</h4>
            <p className={votingDeadlinePassed ? 'deadline-passed' : ''}>
              {new Date(round.voting_deadline).toLocaleString()}
            </p>
            {votingDeadlinePassed && <span className="deadline-status">Closed</span>}
          </div>
        )}
        <div className="deadline-card">
          <h4>Submissions</h4>
          <p className="submission-count">{round.submission_count || 0}</p>
        </div>
        {round.status === RoundStatus.PENDING && (
          <div className="deadline-card">
            <h4>Status</h4>
            <p className="pending-text">Round not started yet</p>
          </div>
        )}
      </div>

      {mySubmission && (
        <div className="my-submission-section">
          <div className="section-header">
            <h3>Your Submission</h3>
            {canEdit() && (
              <div>
                <button onClick={() => setShowEditModal(true)} className="btn-secondary">
                  Edit
                </button>
                <button onClick={handleDeleteSubmission} className="btn-danger">
                  Delete
                </button>
              </div>
            )}
          </div>
          <div className="submission-card my-submission">
            <div className="submission-info">
              <h4>{mySubmission.song_title}</h4>
              <p>{mySubmission.artist_name}</p>
              {mySubmission.album_name && <p className="album-name">{mySubmission.album_name}</p>}
            </div>
            <div className="submission-links">
              <a href={mySubmission.songlink_url} target="_blank" rel="noopener noreferrer" className="link-btn">
                Universal Link
              </a>
              {mySubmission.spotify_url && (
                <a href={mySubmission.spotify_url} target="_blank" rel="noopener noreferrer" className="link-btn spotify">
                  Spotify
                </a>
              )}
              {mySubmission.apple_music_url && (
                <a href={mySubmission.apple_music_url} target="_blank" rel="noopener noreferrer" className="link-btn apple">
                  Apple Music
                </a>
              )}
              {mySubmission.youtube_url && (
                <a href={mySubmission.youtube_url} target="_blank" rel="noopener noreferrer" className="link-btn youtube">
                  YouTube
                </a>
              )}
            </div>
          </div>
        </div>
      )}

      {canSubmit() && (
        <div className="submit-section">
          <button onClick={() => setShowSubmitModal(true)} className="btn-primary btn-large">
            Submit Your Song
          </button>
        </div>
      )}

      {round.status === RoundStatus.COMPLETED && results && (
        <div className="results-section">
          <h3>🏆 Results</h3>
          <div className="results-list">
            {results.results.map((result, index) => (
              <div key={result.submission_id} className={`result-card ${index === 0 ? 'winner' : ''}`}>
                <div className="result-rank">
                  {index === 0 && <span className="trophy">🥇</span>}
                  {index === 1 && <span className="trophy">🥈</span>}
                  {index === 2 && <span className="trophy">🥉</span>}
                  {index > 2 && <span className="rank-number">#{index + 1}</span>}
                </div>
                <div className="result-info">
                  <h4>{result.song_title}</h4>
                  <p>{result.artist_name}</p>
                  <p className="submitter">Submitted by: {result.submitter_name}</p>
                </div>
                <div className="result-stats">
                  <div className="total-points">
                    <span className="points-label">Total Points:</span>
                    <span className="points-value">{result.total_points}</span>
                  </div>
                  <div className="vote-breakdown">
                    {result.first_place_votes > 0 && (
                      <span className="vote-count">🥇 {result.first_place_votes}</span>
                    )}
                    {result.second_place_votes > 0 && (
                      <span className="vote-count">🥈 {result.second_place_votes}</span>
                    )}
                    {result.third_place_votes > 0 && (
                      <span className="vote-count">🥉 {result.third_place_votes}</span>
                    )}
                  </div>
                </div>
                {result.votes_received.length > 0 && (
                  <div className="voters-list">
                    <h5>Votes:</h5>
                    {result.votes_received.map((vote, voteIndex) => (
                      <div key={voteIndex} className="voter-item">
                        <span className="voter-name">{vote.voter_name}</span>
                        <span className="vote-rank">
                          {vote.rank === 1 && '🥇 1st'}
                          {vote.rank === 2 && '🥈 2nd'}
                          {vote.rank === 3 && '🥉 3rd'}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
          <div className="scoring-info">
            <p className="help-text">Scoring: 1st place = 3 points, 2nd place = 2 points, 3rd place = 1 point</p>
          </div>
        </div>
      )}

      {canVote() && (
        <div className="voting-section">
          <div className="section-header">
            <h3>Vote for Your Favorites</h3>
            <p className="help-text">Select and rank up to 3 submissions (excluding your own)</p>
          </div>

          {myVotes && (
            <div className="voting-status">
              <p>✓ You have voted! You can change your votes until the deadline.</p>
              <p className="vote-time">Voted at: {new Date(myVotes.voted_at).toLocaleString()}</p>
            </div>
          )}

          <div className="ranked-selections">
            <h4>Your Rankings:</h4>
            {rankedSubmissions.length === 0 ? (
              <p className="empty-state">Click on submissions below to rank them</p>
            ) : (
              <div className="ranked-list">
                {rankedSubmissions.map((subId, index) => {
                  const submission = round.submissions.find(s => s.id === subId);
                  if (!submission) return null;
                  return (
                    <div key={subId} className="ranked-item">
                      <div className="rank-badge">{index + 1}{index === 0 ? 'st' : index === 1 ? 'nd' : 'rd'}</div>
                      <div className="ranked-song-info">
                        <h5>{submission.song_title}</h5>
                        <p>{submission.artist_name}</p>
                      </div>
                      <div className="rank-controls">
                        {index > 0 && (
                          <button onClick={() => handleMoveUp(subId)} className="btn-icon">↑</button>
                        )}
                        {index < rankedSubmissions.length - 1 && (
                          <button onClick={() => handleMoveDown(subId)} className="btn-icon">↓</button>
                        )}
                        <button onClick={() => handleToggleVote(subId)} className="btn-icon">✕</button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          <button
            onClick={handleCastVotes}
            className="btn-primary btn-large"
            disabled={rankedSubmissions.length === 0}
          >
            {myVotes ? 'Update Votes' : 'Cast Votes'}
          </button>
        </div>
      )}

      <div className="submissions-section">
        <h3>All Submissions ({round.submissions.length})</h3>
        {round.submissions.length === 0 ? (
          <p className="empty-state">No submissions yet. Be the first!</p>
        ) : (
          <div className="submissions-list">
            {round.submissions.map((submission) => {
              const isMySubmission = mySubmission && submission.id === mySubmission.id;
              const rankIndex = rankedSubmissions.indexOf(submission.id);
              const isRanked = rankIndex !== -1;
              const canVoteForThis = canVote() && !isMySubmission;

              return (
                <div
                  key={submission.id}
                  className={`submission-card ${isRanked ? 'ranked' : ''} ${canVoteForThis ? 'votable' : ''} ${isMySubmission ? 'own-submission' : ''}`}
                  onClick={() => canVoteForThis && handleToggleVote(submission.id)}
                >
                  {canVote() && (
                    <div className="vote-indicator">
                      {isMySubmission && <span className="own-badge">Your submission</span>}
                      {isRanked && !isMySubmission && <span className="rank-badge-small">{rankIndex + 1}</span>}
                    </div>
                  )}
                  <div className="submission-info">
                    <h4>{submission.song_title}</h4>
                    <p>{submission.artist_name}</p>
                    {submission.album_name && <p className="album-name">{submission.album_name}</p>}
                    {round.status === RoundStatus.COMPLETED && submission.user_name && (
                      <p className="submitter">Submitted by: {submission.user_name}</p>
                    )}
                  </div>
                  <div className="submission-links">
                    <a href={submission.songlink_url} target="_blank" rel="noopener noreferrer" className="link-btn" onClick={(e) => e.stopPropagation()}>
                      Listen
                    </a>
                    {submission.spotify_url && (
                      <a href={submission.spotify_url} target="_blank" rel="noopener noreferrer" className="link-btn spotify" onClick={(e) => e.stopPropagation()}>
                        Spotify
                      </a>
                    )}
                    {submission.apple_music_url && (
                      <a href={submission.apple_music_url} target="_blank" rel="noopener noreferrer" className="link-btn apple" onClick={(e) => e.stopPropagation()}>
                        Apple
                      </a>
                    )}
                    {submission.youtube_url && (
                      <a href={submission.youtube_url} target="_blank" rel="noopener noreferrer" className="link-btn youtube" onClick={(e) => e.stopPropagation()}>
                        YouTube
                      </a>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {showSubmitModal && (
        <SubmitSongModal
          onClose={() => setShowSubmitModal(false)}
          onSubmit={handleSubmitSong}
        />
      )}

      {showEditModal && mySubmission && (
        <SubmitSongModal
          onClose={() => setShowEditModal(false)}
          onSubmit={handleEditSubmission}
          initialData={mySubmission}
          isEdit={true}
        />
      )}

      {showEditRoundModal && (
        <EditRoundModal
          round={round}
          onClose={() => setShowEditRoundModal(false)}
          onUpdate={handleEditRound}
        />
      )}
    </div>
  );
};

// Submit/Edit Song Modal
const SubmitSongModal: React.FC<{
  onClose: () => void;
  onSubmit: (
    songTitle: string,
    artistName: string,
    albumName: string,
    songlink: string,
    spotify: string,
    appleMusic: string,
    youtube: string,
    artwork: string
  ) => void;
  initialData?: Submission;
  isEdit?: boolean;
}> = ({ onClose, onSubmit, initialData, isEdit = false }) => {
  const [songTitle, setSongTitle] = useState(initialData?.song_title || '');
  const [artistName, setArtistName] = useState(initialData?.artist_name || '');
  const [albumName, setAlbumName] = useState(initialData?.album_name || '');
  const [songlink, setSonglink] = useState(initialData?.songlink_url || '');
  const [spotify, setSpotify] = useState(initialData?.spotify_url || '');
  const [appleMusic, setAppleMusic] = useState(initialData?.apple_music_url || '');
  const [youtube, setYoutube] = useState(initialData?.youtube_url || '');
  const [artwork, setArtwork] = useState(initialData?.artwork_url || '');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit(songTitle, artistName, albumName, songlink, spotify, appleMusic, youtube, artwork);
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content large-modal" onClick={(e) => e.stopPropagation()}>
        <h2>{isEdit ? 'Edit Your Submission' : 'Submit a Song'}</h2>
        <form onSubmit={handleSubmit}>
          <div className="form-row">
            <div className="form-group">
              <label htmlFor="song-title">Song Title *</label>
              <input
                id="song-title"
                type="text"
                value={songTitle}
                onChange={(e) => setSongTitle(e.target.value)}
                required
              />
            </div>
            <div className="form-group">
              <label htmlFor="artist-name">Artist Name *</label>
              <input
                id="artist-name"
                type="text"
                value={artistName}
                onChange={(e) => setArtistName(e.target.value)}
                required
              />
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="album-name">Album Name</label>
            <input
              id="album-name"
              type="text"
              value={albumName}
              onChange={(e) => setAlbumName(e.target.value)}
            />
          </div>

          <div className="form-group">
            <label htmlFor="songlink">Universal Link (song.link) *</label>
            <input
              id="songlink"
              type="url"
              value={songlink}
              onChange={(e) => setSonglink(e.target.value)}
              placeholder="https://song.link/..."
              required
            />
            <p className="help-text">Use song.link to create a universal link that works across all platforms</p>
          </div>

          <div className="form-group">
            <label htmlFor="spotify">Spotify URL</label>
            <input
              id="spotify"
              type="url"
              value={spotify}
              onChange={(e) => setSpotify(e.target.value)}
              placeholder="https://open.spotify.com/track/..."
            />
          </div>

          <div className="form-group">
            <label htmlFor="apple-music">Apple Music URL</label>
            <input
              id="apple-music"
              type="url"
              value={appleMusic}
              onChange={(e) => setAppleMusic(e.target.value)}
              placeholder="https://music.apple.com/..."
            />
          </div>

          <div className="form-group">
            <label htmlFor="youtube">YouTube URL</label>
            <input
              id="youtube"
              type="url"
              value={youtube}
              onChange={(e) => setYoutube(e.target.value)}
              placeholder="https://youtube.com/watch?v=..."
            />
          </div>

          <div className="form-group">
            <label htmlFor="artwork">Artwork URL</label>
            <input
              id="artwork"
              type="url"
              value={artwork}
              onChange={(e) => setArtwork(e.target.value)}
              placeholder="https://..."
            />
          </div>

          <div className="modal-actions">
            <button type="button" onClick={onClose} className="btn-secondary">
              Cancel
            </button>
            <button type="submit" className="btn-primary">
              {isEdit ? 'Save Changes' : 'Submit Song'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

// Edit Round Modal (for pending rounds only)
const EditRoundModal: React.FC<{
  round: RoundDetail;
  onClose: () => void;
  onUpdate: (theme: string, description: string) => void;
}> = ({ round, onClose, onUpdate }) => {
  const [theme, setTheme] = useState(round.theme);
  const [description, setDescription] = useState(round.description || '');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onUpdate(theme, description);
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <h2>Edit Round</h2>
        <p className="help-text">
          Only theme and description can be edited. Deadlines are set automatically when the round starts.
        </p>
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="theme">Theme *</label>
            <input
              id="theme"
              type="text"
              value={theme}
              onChange={(e) => setTheme(e.target.value)}
              placeholder="e.g., Summer Vibes, 90s Throwback"
              required
            />
          </div>

          <div className="form-group">
            <label htmlFor="description">Description</label>
            <textarea
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Describe the theme or rules for this round..."
              rows={3}
            />
          </div>

          <div className="modal-actions">
            <button type="button" onClick={onClose} className="btn-secondary">
              Cancel
            </button>
            <button type="submit" className="btn-primary">
              Save Changes
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default RoundDetailPage;
