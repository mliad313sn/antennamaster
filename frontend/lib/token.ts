/**
 * The account token, in a module both `api.ts` and `saas.ts` can import.
 *
 * It used to live only in `saas.ts`, which imports `apiFetch` from `api.ts` —
 * so `api.ts` could not read it back without a circular import. The practical
 * consequence was that NONE of the planner's own API calls carried the
 * bearer token, and that is not a stylistic problem:
 *
 *   * A signed-in user's click-to-inspect on their own coverage answered 404,
 *     because `/at` is owner-scoped and the request arrived anonymous.
 *   * Worse, the synchronous coverage fallback stored its result with **no
 *     owner at all** — so a study a signed-in user ran that way was readable
 *     by anyone holding the 12-hex id. That is exactly the leak the
 *     owner-scoping exists to prevent, arriving through the back door.
 *     Measured: POST /api/rf/coverage without the header, then GET the raster
 *     as a total stranger → 200.
 *
 * `setToken` stays in `saas.ts`: it does more than write the key (it tells
 * the service worker to purge this account's offline cache), and that belongs
 * with the rest of the session handling.
 */
export const TOKEN_KEY = 'am_token';

export function getToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}

/** `Authorization` for the signed-in account, or nothing when anonymous —
 *  a self-hosted install has no account and must keep working. */
export function authHeaders(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}
