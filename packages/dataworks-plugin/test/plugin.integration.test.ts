import { describe, expect, beforeAll, afterAll } from "bun:test"
import { randomBytes } from "crypto"
import { mkdirSync, rmSync } from "fs"
import { join } from "path"
import { Effect, Layer } from "effect"
import { LayerNode } from "@opencode-ai/core/effect/layer-node"
import { ToolRegistry } from "../../opencode/src/tool/registry"
import { Plugin } from "../../opencode/src/plugin"
import { Config } from "../../opencode/src/config/config"
import { RuntimeFlags } from "../../opencode/src/effect/runtime-flags"
import { Agent } from "../../opencode/src/agent/agent"
import { testEffect } from "../../opencode/test/lib/effect"
import { TestConfig } from "../../opencode/test/fixture/config"
import { InstanceState } from "../../opencode/src/effect/instance-state"
import type { UserID } from "@dataworks-agent/core"
import { dataworksPlugin } from "../src/index"

const tmpDir = join(import.meta.dir, ".plugin-integration-test-tmp")
const dbPath = join(tmpDir, "test.db")
const secretsRoot = join(tmpDir, ".secrets")
const masterKey = randomBytes(32)
const workerTokenSecret = randomBytes(32)

let controlPlaneUrl: string
let workerToken: string
let realConnectionID: string
const workerID = "dry-run-worker-1"

beforeAll(async () => {
  rmSync(tmpDir, { recursive: true, force: true })
  mkdirSync(tmpDir, { recursive: true })

  const serverModule = await import("../../dataworks-control/src/http/server")
  const tokenModule = await import("../../dataworks-control/src/worker/token")
  const connModule = await import("../../dataworks-control/src/data-connection/repo")

  const handle = await serverModule.makeApp({
    dbPath,
    secretsRoot,
    publicOrigin: "http://127.0.0.1:0",
    masterKey: masterKey,
    workerTokenSecret,
    startServer: true,
  })
  controlPlaneUrl = handle.publicOrigin

  const testEmail = `test-plugin-${randomBytes(4).toString("hex")}@example.com`
  await serverModule.createUser({ email: testEmail, password: "testpass123", role: "user" }, handle.db)
  const user = handle.db.get<{ id: string }>("SELECT id FROM dwa_user WHERE email = ?", [testEmail])!

  const connection = await connModule.createDataConnection(handle.db, handle.secrets, {
    user_id: user.id as UserID,
    name: "dwa-staging-conn",
    region: "cn-hangzhou",
    access_key_id: "PLUGIN_AK_FAKE",
    access_key_secret: "PLUGIN_SK_FAKE",
    write_enabled: false,
  })
  realConnectionID = connection.id

  workerToken = tokenModule.signWorkerToken(workerTokenSecret, {
    userID: user.id,
    workerID,
    expires: Date.now() + 30_000,
  })

  process.env.DATAWORKS_CONTROL_PLANE_URL = controlPlaneUrl
  process.env.DATAWORKS_WORKER_TOKEN = workerToken
  process.env.DATAWORKS_WORKER_ID = workerID
})

afterAll(() => {
  process.env.DATAWORKS_CONTROL_PLANE_URL = ""
  process.env.DATAWORKS_WORKER_TOKEN = ""
  process.env.DATAWORKS_WORKER_ID = ""
  try {
    rmSync(tmpDir, { recursive: true, force: true })
  } catch {}
})

const dataworksPluginLayer = Layer.succeed(
  Plugin.Service,
  Plugin.Service.of({
    init: () => Effect.void,
    trigger: ((_name: unknown, _input: unknown, output: unknown) =>
      Effect.succeed(output)) as Plugin.Interface["trigger"],
    list: () =>
      Effect.succeed([
        {
          tool: dataworksPlugin(),
        } as never,
      ]),
  }),
)

const configLayer = TestConfig.layer({
  directories: () => InstanceState.directory.pipe(Effect.map((dir) => [join(dir, ".opencode")])),
})

const root = LayerNode.group([ToolRegistry.node, Agent.node])
const layer = LayerNode.compile(root, [
  [Config.node, configLayer],
  // Partial<Info> collapses under plugin tsconfig pull of opencode; cast keeps test intent.
  [RuntimeFlags.node, RuntimeFlags.layer({ disableDefaultPlugins: true } as never)],
  [Plugin.node, dataworksPluginLayer],
] as never)

const it = testEffect(layer)

describe("dataworks plugin integration", () => {
  it.instance(
    "registers dw_list_projects in ToolRegistry and executes via control plane",
    () =>
      Effect.gen(function* () {
        const registry = yield* ToolRegistry.Service
        const ids = yield* registry.ids()
        expect(ids).toContain("dw_list_projects")

        const tools = yield* registry.all()
        const tool = tools.find((t) => t.id === "dw_list_projects")
        if (!tool) throw new Error("dw_list_projects tool was not found")

        const result = yield* tool.execute(
          { connectionID: realConnectionID } as never,
          {
            sessionID: "ses_test",
            messageID: "msg_test",
            agent: "build",
            abort: new AbortController().signal,
            messages: [],
            metadata: () => Effect.void,
            ask: () => Effect.void,
          } as never,
        )

        expect(result.output).toContain("dwa_staging")
      }),
    { config: {} as never },
    30_000,
  )
})