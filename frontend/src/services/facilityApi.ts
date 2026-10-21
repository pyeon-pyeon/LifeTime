import { apiGet } from './apiClient'
import type { Coordinates } from '../types/location'
import type { FacilityFilter } from '../types/facility'
import type { Facility } from '../types/facility'

export type NearbyFacilityResponse = {
  facilities: Record<string, unknown>[]
  count: number
}

export async function getNearbyFacilities(
  position: Coordinates,
  filter: FacilityFilter = 'all',
  radiusM = 3000,
  signal?: AbortSignal,
): Promise<NearbyFacilityResponse> {
  const params = new URLSearchParams({
    latitude: String(position.latitude),
    longitude: String(position.longitude),
    radius_m: String(radiusM),
  })

  if (filter !== 'all') {
    params.set('facility_type', filter)
  }

  const body = await apiGet(
    `/api/facilities/nearby?${params.toString()}`,
    signal,
  )

  if (
    typeof body !== 'object' ||
    body === null ||
    !('facilities' in body) ||
    !Array.isArray(body.facilities) ||
    !('count' in body) ||
    typeof body.count !== 'number' ||
    !Number.isInteger(body.count) ||
    body.count !== body.facilities.length ||
    !body.facilities.every(
      (item: unknown) =>
        typeof item === 'object' &&
        item !== null &&
        !Array.isArray(item),
    )
  ) {
    throw new Error('주변 시설 API 응답 형식이 올바르지 않습니다.')
  }

  return {
    facilities: body.facilities,
    count: body.count,
  }
}

export type NearbyFacility = Facility & {
  straightDistanceM: number
}

export function toNearbyFacility(
  row: Record<string, unknown>,
): NearbyFacility {
  const {
    id,
    facility_type,
    latitude,
    longitude,
    distance_m,
  } = row

  if (
    typeof id !== 'string' ||
    (facility_type !== 'aed' && facility_type !== 'emergency_room') ||
    typeof latitude !== 'number' ||
    !Number.isFinite(latitude) ||
    Math.abs(latitude) > 90 ||
    typeof longitude !== 'number' ||
    !Number.isFinite(longitude) ||
    Math.abs(longitude) > 180 ||
    typeof distance_m !== 'number' ||
    !Number.isFinite(distance_m) ||
    distance_m < 0
  ) {
    throw new Error('시설 데이터의 ID·좌표·거리 형식을 확인해 주세요.')
  }

  function text(value: unknown, fallback: string) {
    return typeof value === 'string' && value.trim()
      ? value
      : fallback
  }

  return {
    id,
    type: facility_type,
    name: text(row.name, '시설명 정보 없음'),
    address: text(row.address, '주소 정보 없음'),
    detail: text(row.installation_detail, '상세 위치 정보 없음'),
    hours:
      facility_type === 'aed'
        ? '상세 이용시간 조회 전'
        : '운영·수용 여부 별도 확인',
    latitude,
    longitude,
    straightDistanceM: distance_m,
  }
}

export async function getFacilityDetail(
  facilityId: string,
  signal?: AbortSignal,
): Promise<Record<string, unknown>> {
  const body = await apiGet(
    `/api/facilities/${encodeURIComponent(facilityId)}`,
    signal,
  )

  if (
    typeof body !== 'object' ||
    body === null ||
    Array.isArray(body)
  ) {
    throw new Error('시설 상세 API 응답 형식이 올바르지 않습니다.')
  }

  return body as Record<string, unknown>
}