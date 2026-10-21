import assert from 'node:assert/strict'
import test from 'node:test'
import {
  fetchRateLimited,
  parseRetryAfter,
  RATE_LIMIT_EVENT,
  RateLimitCooldown,
  RateLimitError,
  routeRequestCooldown,
} from '../src/services/rateLimit.js'

test('Retry-After accepts seconds and HTTP dates with safe bounds', () => {
  const now = Date.parse('2026-10-21T00:00:00Z')
  assert.equal(parseRetryAfter('12', now), 12)
  assert.equal(parseRetryAfter('0', now), 1)
  assert.equal(parseRetryAfter('99999', now), 3600)
  assert.equal(parseRetryAfter('Wed, 21 Oct 2026 00:00:05 GMT', now), 5)
  assert.equal(parseRetryAfter('invalid', now), 60)
  assert.equal(parseRetryAfter(null, now), 60)
})

test('cooldown expires at the supplied clock time', () => {
  const cooldown = new RateLimitCooldown()
  const start = 10_000
  cooldown.blockFor(5, start)
  assert.equal(cooldown.remainingSeconds(start), 5)
  assert.equal(cooldown.remainingSeconds(start + 4_001), 1)
  assert.equal(cooldown.remainingSeconds(start + 5_000), 0)
})

test('own 429 shows a cooldown and prevents repeat network requests', async () => {
  routeRequestCooldown.clear()
  const originalFetch = globalThis.fetch
  const originalWindow = globalThis.window
  const originalCustomEvent = globalThis.CustomEvent
  let fetchCalls = 0
  const notices = []
  globalThis.fetch = async () => {
    fetchCalls += 1
    return new Response('{}', {
      status: 429,
      headers: { 'Retry-After': '4', 'X-RateLimit-Source': 'lifetime' },
    })
  }
  globalThis.CustomEvent = class extends Event {
    constructor(name, options) { super(name); this.detail = options.detail }
  }
  globalThis.window = {
    dispatchEvent(event) {
      assert.equal(event.type, RATE_LIMIT_EVENT)
      notices.push(event.detail)
      return true
    },
  }
  try {
    await assert.rejects(fetchRateLimited('/api/dev/walking-route'), RateLimitError)
    await assert.rejects(fetchRateLimited('/api/dev/driving-route'), RateLimitError)
    assert.equal(fetchCalls, 1)
    assert.equal(notices.length, 1)
    assert.ok(notices[0].retryAfterSeconds >= 1 && notices[0].retryAfterSeconds <= 4)
  } finally {
    routeRequestCooldown.clear()
    globalThis.fetch = originalFetch
    globalThis.window = originalWindow
    globalThis.CustomEvent = originalCustomEvent
  }
})

test('upstream provider 429 is not treated as the application cooldown', async () => {
  routeRequestCooldown.clear()
  const originalFetch = globalThis.fetch
  let fetchCalls = 0
  globalThis.fetch = async () => {
    fetchCalls += 1
    return new Response('{"message":"provider quota"}', {
      status: 429,
      headers: { 'X-RateLimit-Source': 'upstream' },
    })
  }
  try {
    const response = await fetchRateLimited('/api/dev/walking-route')
    assert.equal(response.status, 429)
    assert.equal(fetchCalls, 1)
    assert.equal(routeRequestCooldown.remainingSeconds(), 0)
  } finally {
    routeRequestCooldown.clear()
    globalThis.fetch = originalFetch
  }
})
