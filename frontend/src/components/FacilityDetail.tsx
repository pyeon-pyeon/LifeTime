import { useEffect, useState } from 'react'
import type { Facility } from '../types/facility'
import type { WalkingRoute } from '../types/route'
import { getFacilityDetail } from '../services/facilityApi'
import Icon from './Icon'

type FacilityDetailProps = {
  facility: Facility
  walkingRoute: WalkingRoute | null
  routeLoading: boolean
  routeError: string | null
  onClose: () => void
  onRouteRequest: () => void
}

type AccessHour = {
  weekday: number
  opens_at: string | null
  closes_at: string | null
  is_24_hours: boolean
  ends_next_day: boolean
}

type DetailData = {
  installationDetail: string | null
  phone: string | null
  accessHours: AccessHour[]
}

type DetailState = {
  facilityId: string
  status: 'success' | 'error'
  data?: DetailData
}

function readText(value: unknown): string | null {
  return typeof value === 'string' && value.trim()
    ? value.trim()
    : null
}

function isAccessHour(value: unknown): value is AccessHour {
  if (typeof value !== 'object' || value === null) return false

  const row = value as Record<string, unknown>

  return (
    typeof row.weekday === 'number' &&
    Number.isInteger(row.weekday) &&
    row.weekday >= 1 &&
    row.weekday <= 7 &&
    (row.opens_at === null || typeof row.opens_at === 'string') &&
    (row.closes_at === null || typeof row.closes_at === 'string') &&
    typeof row.is_24_hours === 'boolean' &&
    typeof row.ends_next_day === 'boolean'
  )
}

function formatHours(hour: AccessHour): string {
  if (hour.is_24_hours) return '24시간'

  if (!hour.opens_at || !hour.closes_at) {
    return '시간 정보 확인 필요'
  }

  const start = hour.opens_at.slice(0, 5)
  const end = hour.closes_at.slice(0, 5)

  if (start === end) return '시간 정보 확인 필요'

  return `${start} ~ ${hour.ends_next_day ? '다음 날 ' : ''}${end}`
}

const WEEKDAYS = ['월', '화', '수', '목', '금', '토', '일']

export default function FacilityDetail({
  facility,
  onClose,
  onRouteRequest,
  walkingRoute,
  routeLoading,
  routeError,
}: FacilityDetailProps) {
  const [detailState, setDetailState] = useState<DetailState | null>(null)
  const [retryCount, setRetryCount] = useState(0)

  useEffect(() => {
    const controller = new AbortController()

    void getFacilityDetail(facility.id, controller.signal)
      .then((body) => {
        if (controller.signal.aborted) return

        const accessHours = Array.isArray(body.access_hours)
          ? body.access_hours.filter(isAccessHour)
          : []

        setDetailState({
          facilityId: facility.id,
          status: 'success',
          data: {
            installationDetail: readText(body.installation_detail),
            phone:
              readText(body.emergency_phone) ??
              readText(body.contact_phone),
            accessHours,
          },
        })
      })
      .catch(() => {
        if (controller.signal.aborted) return

        setDetailState({
          facilityId: facility.id,
          status: 'error',
        })
      })

    return () => controller.abort()
  }, [facility.id, retryCount])

  // 다른 시설의 상세정보가 잠깐 표시되지 않도록 ID를 확인합니다.
  const currentState =
    detailState?.facilityId === facility.id ? detailState : null

  const loading = currentState === null
  const failed = currentState?.status === 'error'
  const detail = currentState?.data
  const accessHours = detail?.accessHours ?? []

  const everyDay24Hours = Array.from(
    { length: 7 },
    (_, index) => index + 1,
  ).every((weekday) =>
    accessHours.some(
      (hour) => hour.weekday === weekday && hour.is_24_hours,
    ),
  )

  const installationDetail =
    detail?.installationDetail ?? facility.detail

  return (
    <section className="detail-sheet" aria-labelledby="detail-heading">
      <div className="detail-top">
        <span className={`facility-category ${facility.type}`}>
          {facility.type === 'aed'
            ? '자동심장충격기 · AED'
            : '응급의료기관'}
        </span>

        <button
          type="button"
          className="icon-button"
          aria-label="시설 상세 닫기"
          onClick={onClose}
        >
          <Icon name="close" />
        </button>
      </div>

      <h2 id="detail-heading">{facility.name}</h2>

      <p className="detail-address">
        <Icon name="pin" size={16} />
        {facility.address}
      </p>

      <div className="detail-facts">
        <div>
          <span>
            {facility.type === 'aed'
              ? '상세 설치 위치'
              : '설치·출입 안내'}
          </span>
          <strong>{installationDetail}</strong>
        </div>

        {facility.type === 'aed' ? (
          <div>
            <span>등록 이용시간</span>

            {loading ? (
              <strong>이용시간을 불러오는 중…</strong>
            ) : failed ? (
              <strong>이용시간을 불러오지 못했어요.</strong>
            ) : everyDay24Hours ? (
              <strong>매일 24시간 이용</strong>
            ) : accessHours.length === 0 ? (
              <strong>등록된 이용시간이 없어요.</strong>
            ) : (
              <ul className="access-hours-list">
                {WEEKDAYS.map((day, index) => {
                  const hours = accessHours.filter(
                    (hour) => hour.weekday === index + 1,
                  )

                  return (
                    <li key={day}>
                      <span>{day}요일</span>
                      <strong>
                        {hours.length > 0
                          ? hours.map(formatHours).join(' / ')
                          : '등록 정보 없음'}
                      </strong>
                    </li>
                  )
                })}
              </ul>
            )}
          </div>
        ) : (
          <div>
            <span>환자 수용 여부</span>
            <strong>방문 전 전화 확인이 필요해요.</strong>
          </div>
        )}

        {detail?.phone && (
          <div>
            <span>시설 연락처</span>
            <a href={`tel:${detail.phone.replace(/[^\d+]/g, '')}`}>
              {detail.phone}
            </a>
          </div>
        )}
      </div>

      <div aria-live="polite">
        {failed && (
          <div className="detail-fetch-error">
            <p>시설 상세정보를 불러오지 못했어요.</p>
            <button
              type="button"
              onClick={() => {
                setDetailState(null)
                setRetryCount((count) => count + 1)
              }}
            >
              다시 시도
            </button>
          </div>
        )}
      </div>

      {facility.type === 'aed' && (
        <p className="detail-notice">
          등록된 이용시간 기준입니다. 현장의 출입 제한이나
          시설 사정에 따라 실제 이용 가능 여부가 다를 수 있어요.
        </p>
      )}

      <button
        type="button"
        className="route-button"
        disabled={routeLoading}
        onClick={onRouteRequest}
      >
        {routeLoading
          ? '경로 계산 중…'
          : facility.type === 'aed'
            ? '도보 경로 보기'
            : '차량 경로 보기'}
        <Icon name="arrow" size={18} />
      </button>

      <div aria-live="polite">
        {walkingRoute && (
          <div className="route-summary">
            <div>
              <span>
                {facility.type === 'aed' ? '예상 보행시간' : '예상 차량 이동시간'}
              </span>
              <strong>
                {Math.max(1, Math.ceil(walkingRoute.durationSec / 60))}분
              </strong>
            </div>

            <div>
              <span>
                {facility.type === 'aed' ? '보행거리' : '차량 이동거리'}
              </span>
              <strong>
                {walkingRoute.distanceM >= 1000
                  ? `${(walkingRoute.distanceM / 1000).toFixed(1)}km`
                  : `${Math.round(walkingRoute.distanceM)}m`}
              </strong>
            </div>
          </div>
        )}

        {routeError && <p className="route-error">{routeError}</p>}
      </div>

      {facility.type === 'emergency_room' && (
        <p className="detail-notice">
          일반 차량의 예상 이동시간입니다. 주차·하차 후 이동시간과
          환자 수용 여부는 포함하지 않습니다. 긴급상황에는 119에 연락하세요.
        </p>
      )}
    </section>
  )
}