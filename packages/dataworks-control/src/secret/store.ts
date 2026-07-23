import { randomBytes } from "crypto"
import { mkdirSync, readFileSync, writeFileSync } from "fs"
import { renameSync, openSync, closeSync, fsyncSync } from "fs"
import { join } from "path"
import { createCipheriv, createDecipheriv, randomFillSync } from "crypto"

export interface SecretStoreConfig {
  readonly root: string
  readonly masterKey: Uint8Array
}

export interface SecretPayload {
  readonly accessKeyId: string
  readonly accessKeySecret: string
}

const MAGIC = Buffer.from([
  0x44, 0x57, 0x41, 0x00, 0x53, 0x45, 0x43, 0x52, 0x45, 0x54, 0x53, 0x76, 0x31, 0x00, 0x00, 0x00,
])
const MAGIC_LENGTH = 16
const NONCE_LENGTH = 12
const TAG_LENGTH = 16
const FILE_NAME = "secrets.dat"
const TMP_NAME = "secrets.dat.tmp"

function readBody(filePath: string): Buffer | null {
  const f = Bun.file(filePath)
  if (!f.size) return null
  return readFileSync(filePath)
}
function decodeBody(body: Buffer, masterKey: Uint8Array): Map<string, SecretPayload> {
  if (body.length < MAGIC_LENGTH + NONCE_LENGTH + TAG_LENGTH) {
    throw new Error("secret store file is corrupted (too short)")
  }
  const magic = body.subarray(0, MAGIC_LENGTH)
  if (!magic.equals(MAGIC)) {
    throw new Error("secret store file has invalid magic/version header")
  }
  const nonce = body.subarray(MAGIC_LENGTH, MAGIC_LENGTH + NONCE_LENGTH)
  const ctWithTag = body.subarray(MAGIC_LENGTH + NONCE_LENGTH)
  const ct = ctWithTag.subarray(0, ctWithTag.length - TAG_LENGTH)
  const tag = ctWithTag.subarray(ctWithTag.length - TAG_LENGTH)

  const decipher = createDecipheriv("aes-256-gcm", masterKey, nonce)
  decipher.setAuthTag(tag)
  const plain = Buffer.concat([decipher.update(ct), decipher.final()])
  const parsed = JSON.parse(plain.toString("utf-8")) as Record<string, { accessKeyId: string; accessKeySecret: string }>
  const refs = new Map<string, SecretPayload>()
  for (const [k, v] of Object.entries(parsed)) refs.set(k, v)
  return refs
}

export class SecretStore {
  private readonly root: string
  private readonly masterKey: Uint8Array
  private refs: Map<string, SecretPayload>

  constructor(root: string, masterKey: Uint8Array, refs: Map<string, SecretPayload>) {
    this.root = root
    this.masterKey = masterKey
    this.refs = refs
  }

  static async test(opts: SecretStoreConfig): Promise<SecretStore> {
    return makeSecretStore(opts)
  }

  async put(id: string, payload: SecretPayload): Promise<void> {
    await this.reload()
    this.refs.set(id, payload)
    await this.flush()
  }

  async ref(id: string): Promise<SecretPayload | undefined> {
    await this.reload()
    return this.refs.get(id)
  }

  async delete(id: string): Promise<void> {
    await this.reload()
    if (!this.refs.delete(id)) return
    await this.flush()
  }

  private async reload(): Promise<void> {
    const body = readBody(join(this.root, FILE_NAME))
    if (body === null) {
      this.refs = new Map()
      return
    }
    this.refs = decodeBody(body, this.masterKey)
  }

  private async flush(): Promise<void> {
    const plain = JSON.stringify(Object.fromEntries(this.refs))
    const nonce = Buffer.alloc(NONCE_LENGTH)
    randomFillSync(nonce)

    const cipher = createCipheriv("aes-256-gcm", this.masterKey, nonce)
    const ct = Buffer.concat([cipher.update(Buffer.from(plain, "utf-8")), cipher.final()])
    const tag = cipher.getAuthTag()

    const body = Buffer.concat([MAGIC, nonce, ct, tag])
    const tmpPath = join(this.root, TMP_NAME)
    const finalPath = join(this.root, FILE_NAME)

    writeFileSync(tmpPath, body)
    const fd = openSync(tmpPath, "r+")
    try {
      fsyncSync(fd)
    } finally {
      closeSync(fd)
    }
    renameSync(tmpPath, finalPath)
  }
}

export async function makeSecretStore(opts: SecretStoreConfig): Promise<SecretStore> {
  if (opts.masterKey.byteLength !== 32) {
    throw new Error("masterKey must be 32 bytes for AES-256-GCM")
  }
  const root = opts.root
  mkdirSync(root, { recursive: true })

  const filePath = join(root, FILE_NAME)
  const body = readBody(filePath)
  const refs = body === null ? new Map<string, SecretPayload>() : decodeBody(body, opts.masterKey)

  return new SecretStore(root, opts.masterKey, refs)
}

export function generateMasterKey(): Uint8Array {
  const out = new Uint8Array(32)
  randomBytes(32).forEach((b, i) => {
    out[i] = b
  })
  return out
}
