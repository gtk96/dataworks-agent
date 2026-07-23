import { describe, expect, test } from "bun:test"
import { checkEgressPolicy } from "../src/proxy/egress"

describe("egress policy", () => {
  test("rejects loopback", () => {
    expect(checkEgressPolicy("http://127.0.0.1:8080", undefined).allowed).toBe(false)
  })

  test("rejects link-local metadata", () => {
    expect(checkEgressPolicy("http://169.254.169.254/", undefined).allowed).toBe(false)
  })

  test("rejects RFC1918", () => {
    expect(checkEgressPolicy("http://10.0.0.5/", undefined).allowed).toBe(false)
  })

  test("rejects unapproved public host", () => {
    expect(checkEgressPolicy("https://example.com/", undefined).allowed).toBe(false)
  })

  test("allows explicit allowlist", () => {
    const allow = new Set(["api.openai.com"])
    expect(checkEgressPolicy("https://api.openai.com/v1", allow).allowed).toBe(true)
  })
})
