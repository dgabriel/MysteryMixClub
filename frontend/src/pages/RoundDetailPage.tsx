import React, { useState, useEffect } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { roundsApi, votesApi } from '../api';
import { RoundDetail, Submission, RoundStatus, SubmissionCreate } from '../types';
import { UserVotesResponse } from '../types/vote';
import { RoundResults } from '../types/results';
import { SongInput as SongInputType, createEmptySongInput } from '../types';
import SongInput from '../components/SongInput';
import StreamingLinks from '../components/StreamingLinks';

const RoundDetailPage: React.FC = () => {
  const { roundId } = useParams<{ roundId: string }>();
  const navigate = useNavigate();
  const [round, setRound] = useState<RoundDetail | null>(null);
  const [mySubmission, setMySubmission] = useState<Submission | null>(null);
  const [myVotes, setMyVotes] = useState<UserVotesResponse | null>(null);
  const [rankedSongs, setRankedSongs] = useState<number[]>([]);
  const [results, setResults] = useState<RoundResults | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showSubmitModal, setShowSubmitModal] = useState(false);
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
      setMySubmission(null);
    }
  };

  const handleSubmitSongs = async (songs: SongInputType[]) => {
    try {
      const submissionData: SubmissionCreate = {
        round_id: Number(roundId),
        songs: songs
      };
      await roundsApi.submitSong(submissionData);
      setShowSubmitModal(false);
      loadRound();
      loadMySubmission();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to submit songs');
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
        setRankedSongs(data.ranked_songs || []);
      }
    } catch (err: any) {
      setMyVotes(null);
      setRankedSongs([]);
    }
  };

  const loadResults = async () => {
    try {
      const data = await roundsApi.getResults(Number(roundId));
      setResults(data);
    } catch (err: any) {
      setResults(null);
    }
  };

  const handleCastVotes = async () => {
    if (rankedSongs.length === 0) {
      setError('Please select at least one song to vote for');
      return;
    }

    try {
      await votesApi.cast({
        round_id: Number(roundId),
        ranked_songs: rankedSongs
      });
      loadMyVotes();
      loadRound();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to cast votes');
    }
  };

  const handleToggleVote = (songId: number) => {
    setRankedSongs(prev => {
      if (prev.includes(songId)) {
        return prev.filter(id => id !== songId);
      } else if (prev.length < 3) {
        return [...prev, songId];
      } else {
        return [...prev.slice(0, 2), songId];
      }
    });
  };

  const handleMoveUp = (songId: number) => {
    setRankedSongs(prev => {
      const index = prev.indexOf(songId);
      if (index <= 0) return prev;
      const newRanking = [...prev];
      [newRanking[index - 1], newRanking[index]] = [newRanking[index], newRanking[index - 1]];
      return newRanking;
    });
  };

  const handleMoveDown = (songId: number) => {
    setRankedSongs(prev => {
      const index = prev.indexOf(songId);
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
    return round.status === RoundStatus.ACTIVE && !round.voting_started_at && !mySubmission;
  };

  const canEdit = () => {
    if (!round || !mySubmission) return false;
    return round.status === RoundStatus.ACTIVE && !round.voting_started_at;
  };

  const canVote = () => {
    if (!round) return false;
    return round.status === RoundStatus.ACTIVE && round.voting_started_at !== null;
  };

  const canEditRound = () => {
    if (!round || !round.is_admin) return false;
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
      await roundsApi.update(Number(roundId), { theme, description });
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
      navigate(-1);
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

  // Get all songs from all submissions for voting
  const getAllSongs = () => {
    if (!round) return [];
    return round.submissions.flatMap(sub =>
      sub.songs.map(song => ({ ...song, submitter_id: sub.user_id, submitter_name: sub.user_name }))
    );
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
  const allSongs = getAllSongs();

  return (
    <div className="round-detail-container">
      {round.league_name && (
        <Link to={`/leagues/${round.league_id}`} className="league-banner">
          {round.league_name}
        </Link>
      )}
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
              View Playlist
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
        {round.songs_per_round && round.songs_per_round > 1 && (
          <div className="deadline-card">
            <h4>Songs Per Submission</h4>
            <p className="submission-count">{round.songs_per_round}</p>
          </div>
        )}
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
                <button onClick={handleDeleteSubmission} className="btn-danger">
                  Delete
                </button>
              </div>
            )}
          </div>
          <div className="my-submission-songs">
            {mySubmission.songs.map((song) => (
              <div key={song.id} className="submission-card my-submission">
                {song.artwork_url && (
                  <img src={song.artwork_url} alt={song.song_title} className="song-artwork" />
                )}
                <div className="submission-info">
                  <h4>{song.song_title}</h4>
                  <p>{song.artist_name}</p>
                  {song.album_name && <p className="album-name">{song.album_name}</p>}
                </div>
                <StreamingLinks song={song} />
              </div>
            ))}
          </div>
        </div>
      )}

      {canSubmit() && (
        <div className="submit-section">
          <button onClick={() => setShowSubmitModal(true)} className="btn-primary btn-large">
            Submit Your {round.songs_per_round && round.songs_per_round > 1 ? 'Songs' : 'Song'}
          </button>
        </div>
      )}

      {round.status === RoundStatus.COMPLETED && results && (
        <div className="results-section">
          <h3>Results</h3>
          <div className="results-list">
            {results.results.map((result, index) => (
              <div key={result.song_id || result.submission_id} className={`result-card ${index === 0 ? 'winner' : ''}`}>
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
                {result.votes_received && result.votes_received.length > 0 && (
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
            <p className="help-text">Select and rank up to 3 songs (excluding your own)</p>
          </div>

          {myVotes && (
            <div className="voting-status">
              <p>✓ You have voted! You can change your votes until the deadline.</p>
              <p className="vote-time">Voted at: {new Date(myVotes.voted_at).toLocaleString()}</p>
            </div>
          )}

          <div className="ranked-selections">
            <h4>Your Rankings:</h4>
            {rankedSongs.length === 0 ? (
              <p className="empty-state">Click on songs below to rank them</p>
            ) : (
              <div className="ranked-list">
                {rankedSongs.map((songId, index) => {
                  const song = allSongs.find(s => s.id === songId);
                  if (!song) return null;
                  return (
                    <div key={songId} className="ranked-item">
                      <div className="rank-badge">{index + 1}{index === 0 ? 'st' : index === 1 ? 'nd' : 'rd'}</div>
                      <div className="ranked-song-info">
                        <h5>{song.song_title}</h5>
                        <p>{song.artist_name}</p>
                      </div>
                      <div className="rank-controls">
                        {index > 0 && (
                          <button onClick={() => handleMoveUp(songId)} className="btn-icon">↑</button>
                        )}
                        {index < rankedSongs.length - 1 && (
                          <button onClick={() => handleMoveDown(songId)} className="btn-icon">↓</button>
                        )}
                        <button onClick={() => handleToggleVote(songId)} className="btn-icon">✕</button>
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
            disabled={rankedSongs.length === 0}
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

              return (
                <div key={submission.id} className={`submission-group ${isMySubmission ? 'own-submission' : ''}`}>
                  {round.status === RoundStatus.COMPLETED && submission.user_name && (
                    <h4 className="submitter-name">Submitted by: {submission.user_name}</h4>
                  )}
                  {isMySubmission && <p className="own-badge">Your submission</p>}

                  <div className="submission-songs">
                    {submission.songs.map((song) => {
                      const rankIndex = rankedSongs.indexOf(song.id);
                      const isRanked = rankIndex !== -1;
                      const canVoteForThis = canVote() && !isMySubmission;

                      return (
                        <div
                          key={song.id}
                          className={`submission-card ${isRanked ? 'ranked' : ''} ${canVoteForThis ? 'votable' : ''}`}
                          onClick={() => canVoteForThis && handleToggleVote(song.id)}
                        >
                          {canVote() && isRanked && !isMySubmission && (
                            <span className="rank-badge-small">{rankIndex + 1}</span>
                          )}
                          {song.artwork_url && (
                            <img src={song.artwork_url} alt={song.song_title} className="song-artwork" />
                          )}
                          <div className="submission-info">
                            <h4>{song.song_title}</h4>
                            <p>{song.artist_name}</p>
                            {song.album_name && <p className="album-name">{song.album_name}</p>}
                          </div>
                          <div onClick={(e) => e.stopPropagation()}>
                            <StreamingLinks song={song} />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {showSubmitModal && round && (
        <SubmitSongsModal
          onClose={() => setShowSubmitModal(false)}
          onSubmit={handleSubmitSongs}
          songsPerRound={round.songs_per_round || 1}
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

// Submit Songs Modal
const SubmitSongsModal: React.FC<{
  onClose: () => void;
  onSubmit: (songs: SongInputType[]) => void;
  songsPerRound: number;
}> = ({ onClose, onSubmit, songsPerRound }) => {
  const [songs, setSongs] = useState<SongInputType[]>(() => {
    const initial = [];
    for (let i = 0; i < songsPerRound; i++) {
      initial.push(createEmptySongInput(i + 1));
    }
    return initial;
  });

  const handleSongChange = (index: number, updatedSong: SongInputType) => {
    const newSongs = [...songs];
    newSongs[index] = updatedSong;
    setSongs(newSongs);
  };

  const handleAddSong = () => {
    if (songs.length < songsPerRound) {
      setSongs([...songs, createEmptySongInput(songs.length + 1)]);
    }
  };

  const handleRemoveSong = (index: number) => {
    if (songs.length > 1) {
      setSongs(songs.filter((_, i) => i !== index));
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    // Validate all songs have required data
    if (songs.length !== songsPerRound) {
      alert(`Please add exactly ${songsPerRound} song(s)`);
      return;
    }

    for (const song of songs) {
      if (!song.song_title || !song.artist_name || !song.songlink_url) {
        alert('Please complete all songs (use the "Find Song" button to fetch links)');
        return;
      }
    }

    onSubmit(songs);
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content large-modal" onClick={(e) => e.stopPropagation()}>
        <h2>Submit {songsPerRound > 1 ? 'Songs' : 'Song'}</h2>
        <p className="help-text">
          This league requires {songsPerRound} song{songsPerRound > 1 ? 's' : ''} per submission
        </p>
        <form onSubmit={handleSubmit}>
          <div className="songs-input-list">
            {songs.map((song, index) => (
              <SongInput
                key={index}
                value={song}
                onChange={(updated) => handleSongChange(index, updated)}
                onRemove={() => handleRemoveSong(index)}
                showRemove={songs.length > 1 && songsPerRound !== songs.length}
                order={index + 1}
              />
            ))}
          </div>

          {songs.length < songsPerRound && (
            <button type="button" onClick={handleAddSong} className="btn-secondary">
              + Add Another Song
            </button>
          )}

          <div className="modal-actions">
            <button type="button" onClick={onClose} className="btn-secondary">
              Cancel
            </button>
            <button type="submit" className="btn-primary">
              Submit {songsPerRound > 1 ? 'Songs' : 'Song'}
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
