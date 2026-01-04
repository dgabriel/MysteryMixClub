import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { leaguesApi, roundsApi } from '../api';
import { LeagueDetail, Round } from '../types';
import { LeagueLeaderboard } from '../types/leaderboard';
import { useAuth } from '../context/AuthContext';

const LeagueDetailPage: React.FC = () => {
  const { leagueId } = useParams<{ leagueId: string }>();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [league, setLeague] = useState<LeagueDetail | null>(null);
  const [rounds, setRounds] = useState<Round[]>([]);
  const [leaderboard, setLeaderboard] = useState<LeagueLeaderboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showEditModal, setShowEditModal] = useState(false);
  const [showCreateRoundModal, setShowCreateRoundModal] = useState(false);

  useEffect(() => {
    if (leagueId) {
      loadLeague();
      loadRounds();
      loadLeaderboard();
    }
  }, [leagueId]);

  const loadLeague = async () => {
    try {
      setLoading(true);
      const data = await leaguesApi.getLeague(Number(leagueId));
      setLeague(data);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load league');
    } finally {
      setLoading(false);
    }
  };

  const loadRounds = async () => {
    try {
      const data = await roundsApi.getLeagueRounds(Number(leagueId));
      setRounds(data);
    } catch (err: any) {
      console.error('Failed to load rounds:', err);
    }
  };

  const loadLeaderboard = async () => {
    try {
      const data = await leaguesApi.getLeaderboard(Number(leagueId));
      setLeaderboard(data);
    } catch (err: any) {
      console.error('Failed to load leaderboard:', err);
    }
  };

  const handleLeave = async () => {
    if (!window.confirm('Are you sure you want to leave this league?')) {
      return;
    }

    try {
      await leaguesApi.leave(Number(leagueId));
      navigate('/leagues');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to leave league');
    }
  };

  const handleDelete = async () => {
    if (!window.confirm('Are you sure you want to delete this league? This cannot be undone!')) {
      return;
    }

    try {
      await leaguesApi.delete(Number(leagueId));
      navigate('/leagues');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to delete league');
    }
  };

  const handleUpdate = async (name: string, description: string) => {
    try {
      await leaguesApi.update(Number(leagueId), { name, description });
      setShowEditModal(false);
      loadLeague();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to update league');
    }
  };

  const copyInviteCode = () => {
    if (league) {
      navigator.clipboard.writeText(league.invite_code);
      alert('Invite code copied to clipboard!');
    }
  };

  const handleCreateRound = async (theme: string, description: string) => {
    try {
      await roundsApi.create({
        league_id: Number(leagueId),
        theme,
        description
      });
      setShowCreateRoundModal(false);
      loadRounds();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to create round');
    }
  };

  const getRoundStatusBadge = (status: string) => {
    const badges: Record<string, string> = {
      pending: 'status-pending',
      active: 'status-active',
      completed: 'status-completed'
    };
    return badges[status] || '';
  };

  if (loading) {
    return <div className="loading">Loading league...</div>;
  }

  if (error || !league) {
    return (
      <div className="error-container">
        <h2>Error</h2>
        <p>{error || 'League not found'}</p>
        <button onClick={() => navigate('/leagues')} className="btn-primary">
          Back to Leagues
        </button>
      </div>
    );
  }

  const isCreator = league.created_by_id === user?.id;

  return (
    <div className="league-detail-container">
      <div className="league-detail-header">
        <div>
          <h1>{league.name}</h1>
          {league.description && <p className="league-description">{league.description}</p>}
        </div>
        <div className="league-actions">
          {league.is_admin && (
            <button onClick={() => setShowEditModal(true)} className="btn-secondary">
              Edit
            </button>
          )}
          {isCreator ? (
            <button onClick={handleDelete} className="btn-danger">
              Delete League
            </button>
          ) : (
            <button onClick={handleLeave} className="btn-secondary">
              Leave League
            </button>
          )}
        </div>
      </div>

      <div className="invite-section">
        <h3>Invite Code</h3>
        <div className="invite-code-box">
          <code>{league.invite_code}</code>
          <button onClick={copyInviteCode} className="btn-secondary">
            Copy
          </button>
        </div>
        <p className="help-text">Share this code with others to invite them to the league</p>
      </div>

      <div className="rounds-section">
        <div className="section-header">
          <h3>Rounds ({rounds.length})</h3>
          {league.is_admin && (
            <button onClick={() => setShowCreateRoundModal(true)} className="btn-primary">
              Create Round
            </button>
          )}
        </div>
        {rounds.length === 0 ? (
          <p className="empty-state">No rounds yet. {league.is_admin && 'Create one to get started!'}</p>
        ) : (
          <div className="rounds-list">
            {rounds.map((round) => (
              <div
                key={round.id}
                className="round-card"
                onClick={() => navigate(`/rounds/${round.id}`)}
              >
                <div className="round-header">
                  <h4>{round.theme}</h4>
                  <span className={`status-badge ${getRoundStatusBadge(round.status)}`}>
                    {round.status.toUpperCase()}
                  </span>
                </div>
                {round.description && <p className="round-description">{round.description}</p>}
                <div className="round-info">
                  <div>
                    <span className="label">Submissions:</span> {round.submission_count || 0}
                  </div>
                  {round.user_has_submitted && (
                    <span className="submitted-badge">✓ Submitted</span>
                  )}
                </div>
                {round.submission_deadline && (
                  <div className="round-deadlines">
                    <div>
                      <span className="label">Submit by:</span>{' '}
                      {new Date(round.submission_deadline).toLocaleDateString()}
                    </div>
                    {round.voting_deadline && (
                      <div>
                        <span className="label">Vote by:</span>{' '}
                        {new Date(round.voting_deadline).toLocaleDateString()}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {leaderboard && leaderboard.completed_rounds_count > 0 && (
        <div className="leaderboard-section">
          <div className="section-header">
            <h3>🏆 Leaderboard</h3>
            <span className="help-text">
              Based on {leaderboard.completed_rounds_count} completed round{leaderboard.completed_rounds_count !== 1 ? 's' : ''}
            </span>
          </div>
          <div className="leaderboard-list">
            {leaderboard.leaderboard.map((entry, index) => (
              <div key={entry.user_id} className={`leaderboard-card ${index === 0 ? 'leader' : ''}`}>
                <div className="leaderboard-rank">
                  {index === 0 && <span className="trophy">🥇</span>}
                  {index === 1 && <span className="trophy">🥈</span>}
                  {index === 2 && <span className="trophy">🥉</span>}
                  {index > 2 && <span className="rank-number">#{index + 1}</span>}
                </div>
                <div className="leaderboard-info">
                  <h4>{entry.user_name}</h4>
                  <p className="participation">
                    Participated in {entry.rounds_participated} round{entry.rounds_participated !== 1 ? 's' : ''}
                  </p>
                </div>
                <div className="leaderboard-points">
                  <span className="points-value">{entry.total_points}</span>
                  <span className="points-label">points</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="members-section">
        <h3>Members ({league.member_count})</h3>
        <div className="members-list">
          {league.members.map((member) => (
            <div key={member.id} className="member-card">
              <div className="member-info">
                <h4>{member.user_name}</h4>
                <p>{member.user_email}</p>
              </div>
              <div className="member-badges">
                {member.is_admin && <span className="admin-badge">ADMIN</span>}
                {member.user_id === league.created_by_id && (
                  <span className="creator-badge">CREATOR</span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {showEditModal && (
        <EditLeagueModal
          league={league}
          onClose={() => setShowEditModal(false)}
          onUpdate={handleUpdate}
        />
      )}

      {showCreateRoundModal && (
        <CreateRoundModal
          onClose={() => setShowCreateRoundModal(false)}
          onCreate={handleCreateRound}
        />
      )}
    </div>
  );
};

// Edit League Modal
const EditLeagueModal: React.FC<{
  league: LeagueDetail;
  onClose: () => void;
  onUpdate: (name: string, description: string) => void;
}> = ({ league, onClose, onUpdate }) => {
  const [name, setName] = useState(league.name);
  const [description, setDescription] = useState(league.description || '');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onUpdate(name, description);
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <h2>Edit League</h2>
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="name">League Name</label>
            <input
              id="name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>

          <div className="form-group">
            <label htmlFor="description">Description</label>
            <textarea
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
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

// Create Round Modal
const CreateRoundModal: React.FC<{
  onClose: () => void;
  onCreate: (theme: string, description: string) => void;
}> = ({ onClose, onCreate }) => {
  const [theme, setTheme] = useState('');
  const [description, setDescription] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onCreate(theme, description);
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <h2>Create New Round</h2>
        <p className="help-text">
          Rounds are created in pending status. Start the round to set deadlines automatically.
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
              Create Round
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default LeagueDetailPage;
