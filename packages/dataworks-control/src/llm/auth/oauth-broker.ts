// STUB: OAuth broker credential injector.
// Server-side refresh/access token store and callback flow.
// Provider adapters must implement it explicitly.
// This stub logs that real broker flow needs staging OAuth credentials.
export function makeOAuthBrokerInjector() {
  return async (input: {
    request: Request
    upstream: URL
    credential: { secret: string }
  }): Promise<Request> => {
    // STUB: In production, this would:
    // 1. Look up stored refresh_token from secret store
    // 2. Call provider's token endpoint to exchange for fresh access_token
    // 3. Cache the new access_token with appropriate TTL
    // 4. Inject the access token into the request
    // Requires: staging OAuth client_id, client_secret, refresh_token
    console.warn("[oauth-broker] STUB: real OAuth broker requires staging OAuth credentials")
    return input.request
  }
}
