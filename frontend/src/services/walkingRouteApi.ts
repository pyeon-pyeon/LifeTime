import type { Coordinates } from '../types/location'
import type { WalkingRoute } from '../types/route'
import { fetchRateLimited } from './rateLimit.js'

type KakaoWalkingResponse = {
  status?: string
  route?: {
    properties?: {
      totalDistance?: number
      totalTime?: number
    }
    legs?: {
      steps?: {
        path?: {
          points?: number[][]
        }
      }[]
    }[]
  }
  message?: string
}

export async function fetchWalkingRoute(
  origin: Coordinates,
  destination: Coordinates,
  signal: AbortSignal,
): Promise<WalkingRoute> {
  const params = new URLSearchParams({
    start_x: String(origin.longitude),
    start_y: String(origin.latitude),
    end_x: String(destination.longitude),
    end_y: String(destination.latitude),
  })

  const response = await fetchRateLimited(
    `/api/dev/walking-route?${params}`,
    { signal },
  )

  const body: KakaoWalkingResponse = await response.json()

  if (!response.ok) {
    throw new Error(body.message ?? '경로 조회에 실패했습니다.')
  }

  if (body.status !== 'OK' || !body.route) {
    const messages: Record<string, string> = {
      SAME_POINT: '출발지와 도착지가 같습니다.',
      START_LINK_NOT_FOUND: '출발지 주변 보행 경로를 찾지 못했습니다.',
      END_LINK_NOT_FOUND: '도착지 주변 보행 경로를 찾지 못했습니다.',
      TOO_FAR_AWAY: '출발지와 도착지가 너무 멉니다.',
      TOO_MANY_SEARCH_LINK: '경로 탐색 범위를 초과했습니다.',
      ROUTE_RESULT_NOT_FOUND: '이동 가능한 보행 경로를 찾지 못했습니다.',
    }

    throw new Error(
      messages[body.status ?? ''] ?? '도보 경로를 확인하지 못했습니다.',
    )
  }

  const distanceM = body.route.properties?.totalDistance
  const durationSec = body.route.properties?.totalTime

  if (
    typeof distanceM !== 'number' ||
    typeof durationSec !== 'number' ||
    !Number.isFinite(distanceM) ||
    !Number.isFinite(durationSec) ||
    distanceM < 0 ||
    durationSec < 0
  ) {
    throw new Error('경로 거리·시간 정보가 올바르지 않습니다.')
  }

  const segments: WalkingRoute['segments'] = []

  for (const leg of body.route.legs ?? []) {
    for (const step of leg.steps ?? []) {
      const points = step.path?.points

      if (!points || points.length < 2) continue

      const segment: [number, number][] = []

      for (const point of points) {
        const [longitude, latitude] = point

        if (
          point.length !== 2 ||
          !Number.isFinite(longitude) ||
          !Number.isFinite(latitude) ||
          Math.abs(longitude) > 180 ||
          Math.abs(latitude) > 90
        ) {
          throw new Error('경로 좌표 정보가 올바르지 않습니다.')
        }

        segment.push([longitude, latitude])
      }

      segments.push(segment)
    }
  }

  if (segments.length === 0) {
    throw new Error('표시할 경로 좌표가 없습니다.')
  }

  return { distanceM, durationSec, segments }
}

type KakaoDrivingResponse = {
  message?: string
  routes?: {
    result_code?: number
    result_msg?: string
    summary?: {
      distance?: number
      duration?: number
    }
    sections?: {
      roads?: {
        vertexes?: number[]
      }[]
    }[]
  }[]
}

export async function fetchDrivingRoute(
  origin: Coordinates,
  destination: Coordinates,
  signal: AbortSignal,
): Promise<WalkingRoute> {
  const params = new URLSearchParams({
    start_x: String(origin.longitude),
    start_y: String(origin.latitude),
    end_x: String(destination.longitude),
    end_y: String(destination.latitude),
  })

  const response = await fetchRateLimited(
    `/api/dev/driving-route?${params}`,
    { signal },
  )

  const body: KakaoDrivingResponse = await response.json()

  if (!response.ok) {
    throw new Error(body.message ?? '차량 경로 조회에 실패했습니다.')
  }

  const route = body.routes?.[0]

  if (!route || route.result_code !== 0) {
    throw new Error(
      route?.result_msg ?? '이동 가능한 차량 경로를 찾지 못했습니다.',
    )
  }

  const distanceM = route.summary?.distance
  const durationSec = route.summary?.duration

  if (
    typeof distanceM !== 'number' ||
    typeof durationSec !== 'number' ||
    !Number.isFinite(distanceM) ||
    !Number.isFinite(durationSec) ||
    distanceM < 0 ||
    durationSec < 0
  ) {
    throw new Error('차량 경로 거리·시간 정보가 올바르지 않습니다.')
  }

  const segments: WalkingRoute['segments'] = []

  for (const section of route.sections ?? []) {
    for (const road of section.roads ?? []) {
      const vertices = road.vertexes

      if (!vertices || vertices.length === 0) continue

      if (vertices.length % 2 !== 0) {
        throw new Error('차량 경로 좌표 형식이 올바르지 않습니다.')
      }

      const segment: [number, number][] = []

      for (let index = 0; index < vertices.length; index += 2) {
        const longitude = vertices[index]
        const latitude = vertices[index + 1]

        if (
          !Number.isFinite(longitude) ||
          !Number.isFinite(latitude) ||
          Math.abs(longitude) > 180 ||
          Math.abs(latitude) > 90
        ) {
          throw new Error('차량 경로 좌표가 올바르지 않습니다.')
        }

        segment.push([longitude, latitude])
      }

      if (segment.length >= 2) {
        segments.push(segment)
      }
    }
  }

  if (segments.length === 0) {
    throw new Error('표시할 차량 경로 좌표가 없습니다.')
  }

  return { distanceM, durationSec, segments }
}
