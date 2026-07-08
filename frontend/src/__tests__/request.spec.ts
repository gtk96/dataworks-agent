/**
 * request 工具函数单元测试
 * 测试 HTTP 客户端的基本功能
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { request, idempotencyKey } from '@/utils/request'

// Mock fetch
const mockFetch = vi.fn()
vi.stubGlobal('fetch', mockFetch)

describe('request', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('发送 GET 请求', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ data: 'test' }),
    })

    const result = await request('/api/test')

    expect(mockFetch).toHaveBeenCalledWith('/api/test', {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
    })
    expect(result).toEqual({ data: 'test' })
  })

  it('发送 POST 请求', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ success: true }),
    })

    const body = { name: 'test' }
    await request('/api/create', { method: 'POST', body })

    expect(mockFetch).toHaveBeenCalledWith('/api/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  })

  it('GET 请求不发送 body', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({}),
    })

    await request('/api/test', { method: 'GET', body: { ignored: true } })

    const callArgs = mockFetch.mock.calls[0]
    expect(callArgs[1].body).toBeUndefined()
  })

  it('处理 HTTP 错误响应', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      statusText: 'Not Found',
      json: () => Promise.resolve({ detail: '资源不存在' }),
    })

    await expect(request('/api/not-found')).rejects.toThrow('资源不存在')
  })

  it('处理网络错误', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      json: () => Promise.reject(new Error('parse error')),
    })

    await expect(request('/api/error')).rejects.toThrow('Internal Server Error')
  })

  it('自定义 headers', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({}),
    })

    await request('/api/test', {
      headers: { 'X-Custom': 'value' },
    })

    const callArgs = mockFetch.mock.calls[0]
    expect(callArgs[1].headers).toEqual({
      'Content-Type': 'application/json',
      'X-Custom': 'value',
    })
  })
})

describe('idempotencyKey', () => {
  it('生成唯一 ID', () => {
    const key1 = idempotencyKey()
    const key2 = idempotencyKey()

    expect(key1).toBeDefined()
    expect(key2).toBeDefined()
    expect(key1).not.toBe(key2)
  })

  it('返回字符串类型', () => {
    const key = idempotencyKey()
    expect(typeof key).toBe('string')
  })
})
