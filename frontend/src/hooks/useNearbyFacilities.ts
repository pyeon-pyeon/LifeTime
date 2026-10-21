import { useCallback, useEffect, useState } from 'react'
import type { Coordinates } from '../types/location'
import type { FacilityFilter } from '../types/facility'
import {
  getNearbyFacilities,
  toNearbyFacility,
} from '../services/facilityApi'
import type { NearbyFacility } from '../services/facilityApi'

export type FacilityLoadStatus =
  | 'idle'
  | 'loading'
  | 'success'
  | 'error'

type Result = {
  key: string
  facilities: NearbyFacility[]
  error: string | null
}

const EMPTY_FACILITIES: NearbyFacility[] = []

export function useNearbyFacilities(
  position: Coordinates | null,
  filter: FacilityFilter,
  radiusM = 3000,
) {
  const latitude = position?.latitude
  const longitude = position?.longitude

  const [attempt, setAttempt] = useState(0)
  const [result, setResult] = useState<Result | null>(null)

  const key =
    latitude === undefined || longitude === undefined
      ? ''
      : `${latitude}:${longitude}:${filter}:${radiusM}:${attempt}`

  useEffect(() => {
    if (latitude === undefined || longitude === undefined) return

    const controller = new AbortController()

    const timer = window.setTimeout(() => {
      void getNearbyFacilities(
        { latitude, longitude },
        filter,
        radiusM,
        controller.signal,
      )
        .then((response) => {
          if (controller.signal.aborted) return

          const facilities = response.facilities
            .map(toNearbyFacility)
            .sort(
              (a, b) => a.straightDistanceM - b.straightDistanceM,
            )

          setResult({
            key,
            facilities,
            error: null,
          })
        })
        .catch((cause: unknown) => {
          if (controller.signal.aborted) return

          setResult({
            key,
            facilities: [],
            error:
              cause instanceof Error
                ? cause.message
                : '시설 조회에 실패했습니다.',
          })
        })
    }, 0)

    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [latitude, longitude, filter, radiusM, key])

  const retry = useCallback(() => {
    setAttempt((value) => value + 1)
  }, [])

  // 검색 조건이 바뀌면 이전 결과를 표시하지 않음
  const current = result?.key === key ? result : null

  const status: FacilityLoadStatus = !key
    ? 'idle'
    : !current
      ? 'loading'
      : current.error
        ? 'error'
        : 'success'

  return {
    facilities: current?.facilities ?? EMPTY_FACILITIES,
    status,
    error: current?.error ?? null,
    retry,
  }
}