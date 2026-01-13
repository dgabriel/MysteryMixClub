"""
Tidal integration service using unofficial tidalapi library.

WARNING: This uses an unofficial API that is not supported by Tidal.
This integration may break at any time without notice.
"""
import tidalapi
import json
import re
from typing import Optional


class TidalService:
    """Service for Tidal OAuth and playlist operations using unofficial tidalapi"""

    def start_device_auth(self) -> dict:
        """
        Start the device authorization flow.
        Returns auth URL and device code for polling.
        """
        session = tidalapi.Session()
        login, future = session.login_oauth()

        return {
            "auth_url": f"https://link.tidal.com/{login.user_code}",
            "device_code": login.device_code,
            "user_code": login.user_code,
            "expires_in": login.expires_in,
            "interval": login.interval,
        }

    def check_auth_status(self, device_code: str) -> Optional[dict]:
        """
        Check if user has completed authorization.
        Returns session data if complete, None if still pending.
        """
        session = tidalapi.Session()

        try:
            # Try to complete the OAuth flow
            session.login_oauth_simple(function=lambda x: device_code)

            if session.check_login():
                return {
                    "user_id": str(session.user.id),
                    "session_data": json.dumps({
                        "token_type": session.token_type,
                        "access_token": session.access_token,
                        "refresh_token": session.refresh_token,
                        "expiry_time": session.expiry_time.isoformat() if session.expiry_time else None,
                    })
                }
        except Exception:
            # Auth not complete yet or failed
            pass

        return None

    def load_session(self, session_data: str) -> tidalapi.Session:
        """Load a session from stored session data"""
        session = tidalapi.Session()
        data = json.loads(session_data)

        session.token_type = data.get("token_type")
        session.access_token = data.get("access_token")
        session.refresh_token = data.get("refresh_token")

        if data.get("expiry_time"):
            from datetime import datetime
            session.expiry_time = datetime.fromisoformat(data["expiry_time"])

        # Check if session is valid and refresh if needed
        if not session.check_login():
            raise ValueError("Tidal session is invalid or expired")

        return session

    def create_playlist(
        self,
        session_data: str,
        name: str,
        description: str,
        track_ids: list[int]
    ) -> dict:
        """
        Create a playlist and add tracks.

        Args:
            session_data: JSON string of stored session
            name: Playlist name
            description: Playlist description
            track_ids: List of Tidal track IDs to add

        Returns:
            Dict with playlist_id and playlist_url
        """
        session = self.load_session(session_data)

        # Create the playlist
        playlist = session.user.create_playlist(name, description)

        # Add tracks if provided
        if track_ids:
            playlist.add(track_ids)

        return {
            "playlist_id": str(playlist.id),
            "playlist_url": f"https://tidal.com/browse/playlist/{playlist.id}",
            "track_count": len(track_ids),
        }

    @staticmethod
    def extract_track_id(tidal_url: str) -> Optional[int]:
        """
        Extract track ID from various Tidal URL formats.

        Supports:
        - https://tidal.com/browse/track/12345678
        - https://listen.tidal.com/track/12345678
        - tidal://track/12345678
        """
        if not tidal_url:
            return None

        patterns = [
            r'tidal\.com/browse/track/(\d+)',
            r'listen\.tidal\.com/track/(\d+)',
            r'tidal://track/(\d+)',
            r'/track/(\d+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, tidal_url)
            if match:
                return int(match.group(1))

        return None

    def get_user_info(self, session_data: str) -> dict:
        """Get basic info about the connected Tidal user"""
        session = self.load_session(session_data)
        user = session.user

        return {
            "user_id": str(user.id),
            "username": getattr(user, 'username', None),
        }


# Singleton instance
tidal_service = TidalService()
