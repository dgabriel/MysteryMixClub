import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { AdminMetricsScreen } from "./AdminMetricsScreen";
import { ApiError, adminGetMetrics, type AdminMetrics } from "../services/api";
import { useAuth } from "../hooks/useAuth";

/**
 * Protected platform-admin route for the metrics snapshot
 * (MysteryMixClub-etz7.3). Already behind ProtectedRoute for auth + onboarding;
 * here we additionally gate on `isPlatformAdmin` and bounce a non-admin to
 * /home, the same defence-in-depth guard AdminRoute uses for a hand-typed URL.
 */
export function AdminMetricsRoute() {
  const { isPlatformAdmin } = useAuth();

  const [metrics, setMetrics] = useState<AdminMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isPlatformAdmin) return;
    let active = true;
    adminGetMetrics()
      .then((snapshot) => {
        if (active) setMetrics(snapshot);
      })
      .catch((err: unknown) => {
        if (active) {
          setError(err instanceof ApiError ? err.message : "couldn't load the metrics.");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [isPlatformAdmin]);

  if (!isPlatformAdmin) {
    return <Navigate to="/home" replace />;
  }

  return <AdminMetricsScreen metrics={metrics} loading={loading} error={error} />;
}
