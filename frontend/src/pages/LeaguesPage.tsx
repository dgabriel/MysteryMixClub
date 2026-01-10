import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { leaguesApi } from '../api';
import { League } from '../types';

const LeaguesPage: React.FC = () => {
  const [leagues, setLeagues] = useState<League[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showJoinModal, setShowJoinModal] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    loadLeagues();
  }, []);

  const loadLeagues = async () => {
    try {
      setLoading(true);
      const data = await leaguesApi.getMyLeagues();
      setLeagues(data);
    } catch (err: any) {
      setError('Failed to load leagues');
    } finally {
      setLoading(false);
    }
  };

  const handleCreateLeague = async (name: string, description: string, songsPerRound: number) => {
    try {
      await leaguesApi.create({ name, description, songs_per_round: songsPerRound });
      setShowCreateModal(false);
      loadLeagues();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to create league');
    }
  };

  const handleJoinLeague = async (inviteCode: string) => {
    try {
      await leaguesApi.join({ invite_code: inviteCode });
      setShowJoinModal(false);
      loadLeagues();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to join league');
    }
  };

  if (loading) {
    return <div className="loading">Loading leagues...</div>;
  }

  return (
    <div className="leagues-container">
      <div className="leagues-header">
        <h1>My Leagues</h1>
        <div className="leagues-actions">
          <button onClick={() => setShowCreateModal(true)} className="btn-primary">
            Create League
          </button>
          <button onClick={() => setShowJoinModal(true)} className="btn-secondary">
            Join League
          </button>
        </div>
      </div>

      {error && <div className="error-message">{error}</div>}

      {leagues.length === 0 ? (
        <div className="empty-state">
          <h2>No Leagues Yet</h2>
          <p>Create a new league or join one using an invite code!</p>
        </div>
      ) : (
        <div className="leagues-grid">
          {leagues.map((league) => (
            <div
              key={league.id}
              className="league-card"
              onClick={() => navigate(`/leagues/${league.id}`)}
            >
              <h3>{league.name}</h3>
              {league.description && <p className="league-description">{league.description}</p>}
              <div className="league-meta">
                <span className="member-count">{league.member_count} members</span>
                {league.is_admin && <span className="admin-badge">ADMIN</span>}
              </div>
              <div className="invite-code">
                Invite Code: <strong>{league.invite_code}</strong>
              </div>
            </div>
          ))}
        </div>
      )}

      {showCreateModal && (
        <CreateLeagueModal
          onClose={() => setShowCreateModal(false)}
          onCreate={handleCreateLeague}
        />
      )}

      {showJoinModal && (
        <JoinLeagueModal
          onClose={() => setShowJoinModal(false)}
          onJoin={handleJoinLeague}
        />
      )}
    </div>
  );
};

// Create League Modal
const CreateLeagueModal: React.FC<{
  onClose: () => void;
  onCreate: (name: string, description: string, songsPerRound: number) => void;
}> = ({ onClose, onCreate }) => {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [songsPerRound, setSongsPerRound] = useState(1);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onCreate(name, description, songsPerRound);
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <h2>Create New League</h2>
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="name">League Name *</label>
            <input
              id="name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              placeholder="e.g., Indie Rock Discovery"
            />
          </div>

          <div className="form-group">
            <label htmlFor="description">Description (optional)</label>
            <textarea
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What's this league about?"
              rows={3}
            />
          </div>

          <div className="form-group">
            <label htmlFor="songsPerRound">Songs Per Round</label>
            <select
              id="songsPerRound"
              value={songsPerRound}
              onChange={(e) => setSongsPerRound(parseInt(e.target.value))}
              className="form-control"
            >
              <option value="1">1 song per submission</option>
              <option value="2">2 songs per submission</option>
              <option value="3">3 songs per submission</option>
              <option value="4">4 songs per submission</option>
              <option value="5">5 songs per submission</option>
            </select>
            <p className="help-text">
              Choose how many songs each member must submit per round. This setting applies to all rounds in this league.
            </p>
          </div>

          <div className="modal-actions">
            <button type="button" onClick={onClose} className="btn-secondary">
              Cancel
            </button>
            <button type="submit" className="btn-primary">
              Create League
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

// Join League Modal
const JoinLeagueModal: React.FC<{
  onClose: () => void;
  onJoin: (inviteCode: string) => void;
}> = ({ onClose, onJoin }) => {
  const [inviteCode, setInviteCode] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onJoin(inviteCode.toUpperCase());
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <h2>Join League</h2>
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="inviteCode">Invite Code</label>
            <input
              id="inviteCode"
              type="text"
              value={inviteCode}
              onChange={(e) => setInviteCode(e.target.value.toUpperCase())}
              required
              placeholder="ABCD1234"
              maxLength={8}
              style={{ textTransform: 'uppercase' }}
            />
          </div>

          <div className="modal-actions">
            <button type="button" onClick={onClose} className="btn-secondary">
              Cancel
            </button>
            <button type="submit" className="btn-primary">
              Join League
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default LeaguesPage;
