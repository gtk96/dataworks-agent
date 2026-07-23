import { expect, test } from "bun:test"

const newSession = await Bun.file(new URL("../new-session.tsx", import.meta.url)).text()
const sessionHeader = await Bun.file(new URL("../../components/session/session-header.tsx", import.meta.url)).text()
const chatHero = await Bun.file(new URL("../../components/dataworks/chat-hero.tsx", import.meta.url)).exists()
const chatHeroCss = await Bun.file(new URL("../../components/dataworks/chat-hero.css", import.meta.url)).exists()

test("draft and session surfaces no longer use the marketing hero", () => {
  expect(newSession).not.toContain("DataWorksChatHero")
  expect(newSession).not.toContain("dwa-hero")
  expect(sessionHeader).toContain("DataWorksScopeBar")
})

test("obsolete hero files are removed", () => {
  expect(chatHero).toBe(false)
  expect(chatHeroCss).toBe(false)
})
