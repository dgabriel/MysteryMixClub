import React, { useState, useEffect, useRef } from 'react';
import { tidalApi, TidalAuthStartResponse } from '../api/tidal';

interface TidalAuthModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

type AuthState = 'warning' | 'connecting' | 'waiting' | 'success' | 'error';

const TidalAuthModal: React.FC<TidalAuthModalProps> = ({ isOpen, onClose, onSuccess }) => {
  const [state, setState] = useState<AuthState>('warning');
  const [authData, setAuthData] = useState<TidalAuthStartResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, []);

  // Reset state when modal opens
  useEffect(() => {
    if (isOpen) {
      setState('warning');
      setAuthData(null);
      setError(null);
    } else {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    }
  }, [isOpen]);

  const startAuth = async () => {
    setState('connecting');
    setError(null);

    try {
      const data = await tidalApi.startAuth();
      setAuthData(data);
      setState('waiting');

      // Open Tidal auth URL in new window
      window.open(data.auth_url, '_blank', 'width=600,height=700');

      // Start polling for completion
      startPolling(data.device_code, data.interval, data.expires_in);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to start Tidal authorization');
      setState('error');
    }
  };

  const startPolling = (deviceCode: string, interval: number, expiresIn: number) => {
    const pollInterval = Math.max(interval, 5) * 1000; // At least 5 seconds
    const expiryTime = Date.now() + (expiresIn * 1000);

    pollIntervalRef.current = setInterval(async () => {
      // Check if expired
      if (Date.now() > expiryTime) {
        if (pollIntervalRef.current) {
          clearInterval(pollIntervalRef.current);
        }
        setError('Authorization expired. Please try again.');
        setState('error');
        return;
      }

      try {
        const result = await tidalApi.completeAuth(deviceCode);
        if (result.success) {
          if (pollIntervalRef.current) {
            clearInterval(pollIntervalRef.current);
          }
          setState('success');
        }
      } catch (err) {
        // Ignore errors during polling - auth not complete yet
      }
    }, pollInterval);
  };

  const handleSuccess = () => {
    onSuccess();
    onClose();
  };

  if (!isOpen) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content tidal-auth-modal" onClick={(e) => e.stopPropagation()}>
        {state === 'warning' && (
          <>
            <h2>Tidal Integration (Beta)</h2>
            <div className="beta-warning">
              <p><strong>Warning:</strong> This feature uses an unofficial library and may stop working at any time.</p>
              <p>Tidal does not officially support third-party playlist creation.</p>
            </div>
            <p className="modal-subtitle">
              <strong>Alternative:</strong> Use "Copy for Tidal" to copy links and add songs manually.
            </p>
            <div className="modal-actions">
              <button className="btn-primary" onClick={startAuth}>
                Connect to Tidal Anyway
              </button>
              <button className="btn-secondary" onClick={onClose}>
                Use Copy/Paste Instead
              </button>
            </div>
          </>
        )}

        {state === 'connecting' && (
          <>
            <h2>Connecting to Tidal...</h2>
            <p>Please wait while we prepare the authorization...</p>
            <div className="loading-spinner"></div>
          </>
        )}

        {state === 'waiting' && authData && (
          <>
            <h2>Authorize in Tidal</h2>
            <p>A new window should have opened. Please log in to Tidal and authorize MysteryMixClub.</p>
            <div className="auth-code-display">
              <p>If the window didn't open, visit:</p>
              <a href={authData.auth_url} target="_blank" rel="noopener noreferrer" className="auth-link">
                {authData.auth_url}
              </a>
            </div>
            <p className="waiting-text">Waiting for authorization...</p>
            <div className="loading-spinner"></div>
            <button className="btn-secondary" onClick={onClose}>
              Cancel
            </button>
          </>
        )}

        {state === 'success' && (
          <>
            <h2>Connected to Tidal!</h2>
            <p>Your Tidal account has been successfully connected.</p>
            <p className="beta-reminder">
              <em>Remember: This is a beta feature using an unofficial API.</em>
            </p>
            <button className="btn-primary" onClick={handleSuccess}>
              Continue
            </button>
          </>
        )}

        {state === 'error' && (
          <>
            <h2>Connection Failed</h2>
            <p className="error-message">{error}</p>
            <div className="modal-actions">
              <button className="btn-primary" onClick={startAuth}>
                Try Again
              </button>
              <button className="btn-secondary" onClick={onClose}>
                Cancel
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default TidalAuthModal;
