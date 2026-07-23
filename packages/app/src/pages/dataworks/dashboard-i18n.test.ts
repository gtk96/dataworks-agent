import { describe, expect, test } from "bun:test"
import { dict as enDict } from "@/i18n/en"
import { dict as zhDict } from "@/i18n/zh"

describe("dataworks i18n coverage", () => {
  const requiredKeys = [
    "dataworks.chat.hero",
    "dataworks.chat.send",
    "dataworks.chat.attach",
    "dataworks.chat.scope.change",
    "dataworks.chat.model.change",
    "dataworks.chat.env.prod",
    "dataworks.chat.env.staging",
    "dataworks.chat.env.dev",
    "dataworks.chat.env.prod.full",
    "dataworks.chat.env.staging.full",
    "dataworks.chat.env.dev.full",
    "dataworks.chat.hints.try",
    "dataworks.chat.footer.scope",
    "dataworks.chat.footer.shortcut",
    "dataworks.chat.footer.privacy",
    "dataworks.chat.footer.compliance",
    "dataworks.chat.placeholder.aria",
    "dataworks.chat.subtitle",
    "dataworks.chat.prompt.tables",
    "dataworks.chat.prompt.jobs",
    "dataworks.chat.prompt.orders",
    "dataworks.chat.prompt.ping",
    "dataworks.chat.label.tables",
    "dataworks.chat.label.jobs",
    "dataworks.chat.label.orders",
    "dataworks.chat.label.ping",
    "dataworks.chat.hint.tables",
    "dataworks.chat.hint.jobs",
    "dataworks.chat.hint.orders",
    "dataworks.chat.hint.ping",
    "dataworks.chat.category.tables",
    "dataworks.chat.category.jobs",
    "dataworks.chat.category.orders",
    "dataworks.chat.category.ping",
    "dataworks.workbench.untitledQuery",
  ]

  test.each(requiredKeys)("zh has %s", (key) => {
    expect((zhDict as Record<string, string>)[key]).toBeTruthy()
  })

  test.each(requiredKeys)("en has %s", (key) => {
    expect((enDict as Record<string, string>)[key]).toBeTruthy()
  })

  test("en has no extra keys not present in zh", () => {
    const zhKeys = new Set(Object.keys(zhDict))
    const extras = Object.keys(enDict).filter((k) => !zhKeys.has(k))
    expect(extras).toEqual([])
  })
})
