import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

/**
 * Listen for deep-link navigations forwarded from the Electron main process
 * (metacrm:// protocol URLs). Registers once on mount and navigates the
 * renderer to the target path when a deep-link event arrives.
 *
 * Safe to call in a browser context — `window.metacrm?.onDeepLink` is
 * undefined there and the effect becomes a no-op.
 */
export function useDeepLink(): void {
  const navigate = useNavigate();

  useEffect(() => {
    window.metacrm?.onDeepLink?.((target) => {
      navigate(target, { replace: true });
    });
    // onDeepLink adds a listener; Electron IPC listeners are process-scoped
    // and removed when the window is destroyed, so no cleanup is needed.
  }, [navigate]);
}
