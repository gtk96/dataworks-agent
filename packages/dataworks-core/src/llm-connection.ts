// LLM Connection types — represents a user's provider credential safe proxy configuration.

export type AuthStrategy =
  | "static_header"
  | "query_key"
  | "aws_sigv4"
  | "gcp_oauth"
  | "oauth_broker"

export type DataClassificationLevel =
  | "prompt_only"
  | "workspace_files"
  | "workspace_files_and_artifacts"

export interface LlmCredential {
  readonly secret: string
  readonly headerName?: string
  readonly headerScheme?: "bearer" | "basic" | "apikey" | "named"
  readonly region?: string
  readonly service?: string
}

export namespace LlmConnection {
  export interface Info {
    readonly id: string
    readonly user_id: string
    readonly provider_id: string
    readonly name: string
    readonly upstream_origin: string
    readonly auth_strategy: AuthStrategy
    readonly secret_ref: string
    readonly enabled: boolean
    readonly allowed_models: string[]
    readonly data_classification_allowlist: DataClassificationLevel
    readonly time_created: number
    readonly time_updated: number
  }

  export interface CreateInput {
    readonly user_id: string
    readonly provider_id: string
    readonly name: string
    readonly upstream_origin: string
    readonly auth_strategy: AuthStrategy
    readonly secret_ref: string
    readonly allowed_models: string[]
    readonly data_classification_allowlist: DataClassificationLevel
    readonly enabled?: boolean
  }

  export interface UpdateInput {
    readonly name?: string
    readonly upstream_origin?: string
    readonly auth_strategy?: AuthStrategy
    readonly secret_ref?: string
    readonly enabled?: boolean
    readonly allowed_models?: string[]
    readonly data_classification_allowlist?: DataClassificationLevel
  }
}

// Well-known provider identifiers
export const KNOWN_PROVIDERS = [
  "openai",
  "anthropic",
  "google",
  "azure-openai",
  "aws-bedrock",
  "groq",
  "openrouter",
  "ollama",
  "mistral",
  "cohere",
  "deepseek",
] as const

export type KnownProvider = (typeof KNOWN_PROVIDERS)[number]

export interface ProviderInfo {
  readonly id: string
  readonly name: string
  readonly auth_strategy: AuthStrategy | null
  readonly description: string
}

export const PROVIDER_CATALOG: Record<string, ProviderInfo> = {
  openai: {
    id: "openai",
    name: "OpenAI",
    auth_strategy: "static_header",
    description: "OpenAI API with bearer token authentication",
  },
  anthropic: {
    id: "anthropic",
    name: "Anthropic",
    auth_strategy: "static_header",
    description: "Anthropic API with bearer token authentication",
  },
  "azure-openai": {
    id: "azure-openai",
    name: "Azure OpenAI",
    auth_strategy: "static_header",
    description: "Azure OpenAI Service with API key",
  },
  "aws-bedrock": {
    id: "aws-bedrock",
    name: "AWS Bedrock",
    auth_strategy: "aws_sigv4",
    description: "AWS Bedrock with SigV4 signing",
  },
  google: {
    id: "google",
    name: "Google AI",
    auth_strategy: "gcp_oauth",
    description: "Google AI (Gemini) with OAuth token",
  },
  groq: {
    id: "groq",
    name: "Groq",
    auth_strategy: "static_header",
    description: "Groq API with bearer token",
  },
  openrouter: {
    id: "openrouter",
    name: "OpenRouter",
    auth_strategy: "static_header",
    description: "OpenRouter with bearer token",
  },
  ollama: {
    id: "ollama",
    name: "Ollama",
    auth_strategy: null,
    description: "Ollama local deployment (not available in multi-user mode)",
  },
  mistral: {
    id: "mistral",
    name: "Mistral AI",
    auth_strategy: "static_header",
    description: "Mistral AI API with bearer token",
  },
  cohere: {
    id: "cohere",
    name: "Cohere",
    auth_strategy: "static_header",
    description: "Cohere API with bearer token",
  },
  deepseek: {
    id: "deepseek",
    name: "DeepSeek",
    auth_strategy: "static_header",
    description: "DeepSeek API with bearer token",
  },
}
