import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { HomeScreen } from "./HomeScreen";
import { useAuth } from "../hooks/useAuth";

/**
 * Protected home route. Wires HomeScreen's session actions to the auth context.
 * Both actions invalidate the session server-side, clear the in-memory token,
 * and return to /login. `busy` disables the controls during the calls.
 */
export function HomeRoute() {
  const navigate = useNavigate();
  const { logout, logoutAll } = useAuth();
  const [busy, setBusy] = useState(false);

  async function handleLogout() {
    setBusy(true);
    try {
      await logout();
      navigate("/login", { replace: true });
    } finally {
      setBusy(false);
    }
  }

  async function handleLogoutAll() {
    setBusy(true);
    try {
      await logoutAll();
      navigate("/login", { replace: true });
    } finally {
      setBusy(false);
    }
  }

  return <HomeScreen onLogout={handleLogout} onLogoutAll={handleLogoutAll} busy={busy} />;
}
