// STUB: AWS SigV4 credential injector.
// Full signing requires staging AWS credentials (access_key_id, secret_access_key, session_token, region).
// This stub exposes the CredentialInjector interface but logs that real signing needs staging credentials.
// The actual signing flow would use @aws-sdk/signature-v4 or equivalent.
export function makeAwsSigV4Injector() {
  return async (input: {
    request: Request
    upstream: URL
    credential: { secret: string; region?: string; service?: string }
  }): Promise<Request> => {
    // STUB: In production, this would sign the request using AWS SigV4 algorithm
    // Requires: staging AWS credentials (access_key_id, secret_access_key, session_token)
    // and configured region/service (e.g., "us-east-1" / "bedrock")
    // For now, just forward the request as-is with a note
    console.warn("[aws-sigv4] STUB: real signing requires staging AWS credentials")
    return input.request
  }
}
