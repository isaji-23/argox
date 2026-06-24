// Dashboard credential store.
//
// The Collector authenticates every query request with an
// `Authorization: Bearer <credential>` header (see
// `argox-project/docs/collector/auth.md`). A human operator pastes an API key
// holding the `read` scope; it is persisted to `localStorage` (mirroring the
// `argox.theme` / `argox.route` pattern) and attached to every API call. No
// credential is ever baked into the served bundle.

const STORAGE_KEY = 'argox.apikey';

// Admin-scoped credential used only by the key-management screen (DASH-06).
// Kept in a slot separate from the `read` key so an operator's day-to-day
// read credential and their admin credential do not collide. Any
// `admin`-scoped key works, including the break-glass bootstrap key.
const ADMIN_STORAGE_KEY = 'argox.adminkey';

/** Fires whenever the stored token changes (set or cleared). */
export const TOKEN_CHANGED_EVENT = 'argox:token-changed';

/** Fires whenever the stored admin token changes (set or cleared). */
export const ADMIN_TOKEN_CHANGED_EVENT = 'argox:admin-token-changed';

/**
 * Fires when an API call is rejected for missing/insufficient credentials
 * (HTTP 401/403), so the UI can prompt for a key.
 */
export const AUTH_REQUIRED_EVENT = 'argox:auth-required';

/** Module-level bus so `api.ts` can signal and React components can listen. */
export const authBus = new EventTarget();

/** Returns the stored API key, or `null` when none is set. */
export function getToken(): string | null {
  return localStorage.getItem(STORAGE_KEY);
}

/**
 * Returns true when `token` is safe to send in an `Authorization` header.
 *
 * The browser `Headers` constructor throws a `TypeError` on control characters
 * (e.g. a stray CR/LF from a bad paste), which would escape the `APIError`
 * flow. Reject any control character up front so the UI can complain cleanly.
 * An empty string is valid (it clears the stored key).
 */
export function isValidToken(token: string): boolean {
  // eslint-disable-next-line no-control-regex
  return !/[\x00-\x1F\x7F]/.test(token.trim());
}

/**
 * Persists an API key (trimmed) or clears it when the value is empty.
 *
 * Returns false without storing anything when the value contains control
 * characters; otherwise stores it and returns true.
 */
export function setToken(token: string): boolean {
  const trimmed = token.trim();
  if (!isValidToken(trimmed)) return false;
  if (trimmed) {
    localStorage.setItem(STORAGE_KEY, trimmed);
  } else {
    localStorage.removeItem(STORAGE_KEY);
  }
  authBus.dispatchEvent(new Event(TOKEN_CHANGED_EVENT));
  return true;
}

/** Removes the stored API key. */
export function clearToken(): void {
  localStorage.removeItem(STORAGE_KEY);
  authBus.dispatchEvent(new Event(TOKEN_CHANGED_EVENT));
}

/** Notifies listeners that a request failed authentication/authorization. */
export function signalAuthRequired(): void {
  authBus.dispatchEvent(new Event(AUTH_REQUIRED_EVENT));
}

/** Returns the stored admin key, or `null` when none is set. */
export function getAdminToken(): string | null {
  return localStorage.getItem(ADMIN_STORAGE_KEY);
}

/**
 * Persists an admin key (trimmed) or clears it when the value is empty.
 *
 * Returns false without storing anything when the value contains control
 * characters; otherwise stores it and returns true. Same validation as the
 * read key — see {@link isValidToken}.
 */
export function setAdminToken(token: string): boolean {
  const trimmed = token.trim();
  if (!isValidToken(trimmed)) return false;
  if (trimmed) {
    localStorage.setItem(ADMIN_STORAGE_KEY, trimmed);
  } else {
    localStorage.removeItem(ADMIN_STORAGE_KEY);
  }
  authBus.dispatchEvent(new Event(ADMIN_TOKEN_CHANGED_EVENT));
  return true;
}

/** Removes the stored admin key. */
export function clearAdminToken(): void {
  localStorage.removeItem(ADMIN_STORAGE_KEY);
  authBus.dispatchEvent(new Event(ADMIN_TOKEN_CHANGED_EVENT));
}
