import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  return {
    plugins: [
      react(),
      {
        name: 'local-facility-route',
        configureServer(server) {
          server.middlewares.use(async (req, res, next) => {
            const url = new URL(
              req.url ?? '/',
              'http://localhost',
            )

            const isDriving = url.pathname === '/api/dev/driving-route'
            const isWalking = url.pathname === '/api/dev/walking-route'

            if (!isDriving && !isWalking) {
              next()
              return
            }

            res.setHeader('Content-Type', 'application/json; charset=utf-8')
            res.setHeader('Cache-Control', 'no-store')

            function respond(status: number, body: unknown) {
              res.statusCode = status
              res.end(JSON.stringify(body))
            }

            if (req.method !== 'GET') {
              respond(405, { message: 'GET 요청만 지원합니다.' })
              return
            }

            const apiKey = env.KAKAO_REST_API_KEY?.trim()

            if (!apiKey) {
              respond(503, {
                message: '.env.local에 KAKAO_REST_API_KEY가 필요합니다.',
              })
              return
            }

            const names = [
              'start_x',
              'start_y',
              'end_x',
              'end_y',
            ] as const

            const values = names.map((name) => {
              const raw = url.searchParams.get(name)
              return raw === null || raw.trim() === ''
                ? Number.NaN
                : Number(raw)
            })

            const valid = values.every((value, index) => {
              const limit = index % 2 === 0 ? 180 : 90
              return Number.isFinite(value) && Math.abs(value) <= limit
            })

            if (!valid) {
              respond(400, { message: '출발·도착 좌표를 확인해 주세요.' })
              return
            }

            const upstream = new URL(
              isDriving
                ? 'https://apis-navi.kakaomobility.com/v1/directions'
                : 'https://dapi.kakao.com/v2/routing/walk',
            )

            if (isDriving) {
              upstream.searchParams.set('origin', `${values[0]},${values[1]}`)
              upstream.searchParams.set('destination', `${values[2]},${values[3]}`)
              upstream.searchParams.set('priority', 'TIME')
              upstream.searchParams.set('summary', 'false')
              upstream.searchParams.set('alternatives', 'false')
            } else {
              names.forEach((name, index) => {
                upstream.searchParams.set(name, String(values[index]))
              })

              upstream.searchParams.set('input_coord', 'WGS84')
              upstream.searchParams.set('output_coord', 'WGS84')
            }

            try {
              const response = await fetch(upstream, {
                headers: {
                  Authorization: `KakaoAK ${apiKey}`,
                },
                signal: AbortSignal.timeout(15000),
              })

              if (!response.ok) {
                respond(response.status === 429 ? 429 : 502, {
                  message:
                    `카카오 경로 요청 실패 (${response.status}). ` +
                    'REST 키·사용 권한·쿼터를 확인해 주세요.',
                })
                return
              }

              const body: unknown = await response.json()
              respond(200, body)
            } catch {
              respond(502, {
                message: '경로 서버에 연결하지 못했거나 시간이 초과됐습니다.',
              })
            }
          })
        },
      },
    ],
    server: {
      host: 'localhost',
      port: 5174,
      strictPort: true,
    },
  }
})