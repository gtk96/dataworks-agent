import { generateMasterKey } from "./store"

const SERVICE = "dataworks-agent"
const ACCOUNT = "master-key-v1"

export class KeyringUnavailable extends Error {
  constructor(message: string, readonly instructions: string) {
    super(message)
    this.name = "KeyringUnavailable"
  }
}

export interface SystemKeyringBackend {
  getPassword(service: string, account: string): string | null
  setPassword(service: string, account: string, password: string): void
}

let cachedBackend: SystemKeyringBackend | null = null
let backendAttempted = false

async function loadBackend(): Promise<SystemKeyringBackend | null> {
  if (backendAttempted) return cachedBackend
  backendAttempted = true
  try {
    const mod = await import("@napi-rs/keyring")
    if (typeof mod?.Entry !== "function") return null
    cachedBackend = {
      getPassword: (service, account) => new mod.Entry(service, account).getPassword(),
      setPassword: (service, account, password) => new mod.Entry(service, account).setPassword(password),
    }
    return cachedBackend
  } catch {
    return null
  }
}

export interface KeyringOptions {
  readonly backend?: SystemKeyringBackend
  readonly generate?: () => Uint8Array
  readonly account?: string
  readonly service?: string
}

export async function loadOrCreateMasterKey(opts: KeyringOptions = {}): Promise<Uint8Array> {
  const backend = opts.backend ?? (await loadBackend())
  const service = opts.service ?? SERVICE
  const account = opts.account ?? ACCOUNT

  if (!backend) {
    throw new KeyringUnavailable(
      `OS credential store unavailable for service=${service} account=${account}`,
      "Install or unlock the OS credential store (e.g. Windows Credential Manager, macOS Keychain, libsecret) and restart, or run with --passphrase to provide an Argon2id-derived key explicitly.",
    )
  }

  let existing: string | null = null
  try {
    existing = backend.getPassword(service, account)
  } catch (cause) {
    throw new KeyringUnavailable(
      `OS credential store unreachable: ${cause}`,
      "Install or unlock the OS credential store (e.g. Windows Credential Manager, macOS Keychain, libsecret) and restart, or run with --passphrase to provide an Argon2id-derived key explicitly.",
    )
  }
  if (existing) {
    const bytes = base64ToBytes(existing)
    if (bytes.byteLength !== 32) {
      const fresh = (opts.generate ?? generateMasterKey)()
      try {
        backend.setPassword(service, account, bytesToBase64(fresh))
      } catch (cause) {
        throw new KeyringUnavailable(
          `OS credential store unreachable: ${cause}`,
          "Install or unlock the OS credential store (e.g. Windows Credential Manager, macOS Keychain, libsecret) and restart, or run with --passphrase to provide an Argon2id-derived key explicitly.",
        )
      }
      return fresh
    }
    return bytes
  }

  const fresh = (opts.generate ?? generateMasterKey)()
  try {
    backend.setPassword(service, account, bytesToBase64(fresh))
  } catch (cause) {
    throw new KeyringUnavailable(
      `OS credential store unreachable: ${cause}`,
      "Install or unlock the OS credential store (e.g. Windows Credential Manager, macOS Keychain, libsecret) and restart, or run with --passphrase to provide an Argon2id-derived key explicitly.",
    )
  }
  return fresh
}

function bytesToBase64(bytes: Uint8Array): string {
  let bin = ""
  for (let i = 0; i < bytes.byteLength; i++) bin += String.fromCharCode(bytes[i]!)
  return btoa(bin)
}

function base64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}
