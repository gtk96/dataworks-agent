import { hash, verify } from "@node-rs/argon2"

const HASH_OPTIONS = {
  memoryCost: 19456,
  timeCost: 2,
  parallelism: 1,
  outputLen: 32,
} as const

export async function hashPassword(password: string): Promise<string> {
  return hash(password, HASH_OPTIONS)
}

export async function verifyPassword(hash: string, password: string): Promise<boolean> {
  return verify(hash, password)
}
