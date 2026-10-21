import { useEffect, useRef, useState } from 'react'
import type { Coordinates } from '../types/location'
import type { Facility } from '../types/facility'
import type { WalkingRoute } from '../types/route'
import {
  fetchWalkingRoute,
  fetchDrivingRoute,
} from '../services/walkingRouteApi'
export type RankedFacility = {
  facilityId: string
  route: WalkingRoute
}

type RankingState = {
  key: string
  status: 'loading' | 'success'
  completed: number
  results: RankedFacility[]
  failedIds: string[]
}

export function useWalkingRanking(
  origin: Coordinates | null,
  candidates: Facility[],
  enabled: boolean,
) {
  const [state, setState] = useState<RankingState | null>(null)

  const controllerRef = useRef<AbortController | null>(null)
  const runningRef = useRef(false)

  const key = enabled && origin && candidates.length > 0
    ? JSON.stringify([
        origin.latitude,
        origin.longitude,
        candidates.map((facility) => [
          facility.id,
          facility.type,
          facility.latitude,
          facility.longitude,
        ]),
      ])
    : ''

  useEffect(() => {
    return () => {
      controllerRef.current?.abort()
      runningRef.current = false
    }
  }, [key])

  const current = state?.key === key ? state : null

  async function compare() {
    if (
      !origin ||
      !key ||
      runningRef.current ||
      current?.status === 'success'
    ) {
      return
    }

    controllerRef.current?.abort()

    const controller = new AbortController()
    controllerRef.current = controller
    runningRef.current = true

    const results: RankedFacility[] = []
    const failedIds: string[] = []

    let nextIndex = 0
    let completed = 0

    setState({
      key,
      status: 'loading',
      completed: 0,
      results: [],
      failedIds: [],
    })

    async function worker() {
      while (!controller.signal.aborted) {
        const index = nextIndex++
        const facility = candidates[index]

        if (!facility) return

        try {
          const fetchRoute =
            facility.type === 'emergency_room'
                ? fetchDrivingRoute
                : fetchWalkingRoute

          const route = await fetchRoute(
            origin!,
            facility,
            controller.signal,
            )

          if (controller.signal.aborted) return

          results.push({
            facilityId: facility.id,
            route,
          })
        } catch {
          if (controller.signal.aborted) return
          failedIds.push(facility.id)
        }

        completed += 1

        if (!controller.signal.aborted) {
          setState({
            key,
            status: 'loading',
            completed,
            results: [],
            failedIds: [...failedIds],
          })
        }
      }
    }

    try {
      await Promise.all([
        worker(),
        worker(),
      ])

      if (controller.signal.aborted) return

      results.sort(
        (a, b) =>
          a.route.durationSec - b.route.durationSec ||
          a.route.distanceM - b.route.distanceM ||
          a.facilityId.localeCompare(b.facilityId),
      )

      setState({
        key,
        status: 'success',
        completed,
        results,
        failedIds,
      })
    } finally {
      if (controllerRef.current === controller) {
        runningRef.current = false
      }
    }
  }

  return {
    compare,
    loading: current?.status === 'loading',
    done: current?.status === 'success',
    completed: current?.completed ?? 0,
    results: current?.results ?? [],
    failedIds: current?.failedIds ?? [],
  }
}