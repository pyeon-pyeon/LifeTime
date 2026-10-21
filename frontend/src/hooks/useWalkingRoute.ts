import { useEffect, useRef, useState } from 'react'
import type { Coordinates } from '../types/location'
import type { Facility } from '../types/facility'
import type { WalkingRoute } from '../types/route'
import {
  fetchWalkingRoute,
  fetchDrivingRoute,
} from '../services/walkingRouteApi'

type RouteResult = {
  key: string
  status: 'loading' | 'success' | 'error'
  route: WalkingRoute | null
  error: string | null
}

export function useWalkingRoute(
  origin: Coordinates | null,
  destination:
    | (Coordinates & Pick<Facility, 'id' | 'type'>)
    | undefined,
) {
  const [result, setResult] = useState<RouteResult | null>(null)
  const controllerRef = useRef<AbortController | null>(null)

  const key =
    origin && destination
      ? [
          origin.latitude,
          origin.longitude,
          destination.id,
          destination.type,
          destination.latitude,
          destination.longitude,
        ].join(':')
      : ''

  useEffect(() => {
    return () => {
      controllerRef.current?.abort()
    }
  }, [key])

  async function requestRoute() {
    if (!origin || !destination || !key) return

    controllerRef.current?.abort()

    const controller = new AbortController()
    controllerRef.current = controller

    setResult({
      key,
      status: 'loading',
      route: null,
      error: null,
    })

    try {
      const fetchRoute =
        destination.type === 'emergency_room'
          ? fetchDrivingRoute
          : fetchWalkingRoute

      const route = await fetchRoute(
        origin,
        destination,
        controller.signal,
      )

      if (controller.signal.aborted) return

      setResult({
        key,
        status: 'success',
        route,
        error: null,
      })
    } catch (cause) {
      if (controller.signal.aborted) return

      setResult({
        key,
        status: 'error',
        route: null,
        error:
          cause instanceof Error
            ? cause.message
            : '경로 조회에 실패했습니다.',
      })
    }
  }

  const current = result?.key === key ? result : null

  return {
    route: current?.route ?? null,
    loading: current?.status === 'loading',
    error: current?.error ?? null,
    requestRoute,
  }
}