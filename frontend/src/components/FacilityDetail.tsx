import type { Facility } from '../types/facility'
import Icon from './Icon'
import type { WalkingRoute } from '../types/route'

type FacilityDetailProps = {
  facility: Facility
  walkingRoute: WalkingRoute | null
  routeLoading: boolean
  routeError: string | null
  onClose: () => void
  onRouteRequest: () => void
}

export default function FacilityDetail({
  facility,
  onClose,
  onRouteRequest,
  walkingRoute,
  routeLoading,
  routeError,
}: FacilityDetailProps) {
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
          <span>설치·출입 위치</span>
          <strong>{facility.detail}</strong>
        </div>

        <div>
          <span>
            {facility.type === 'aed' ? '등록 이용시간' : '운영 정보'}
          </span>
          <strong>{facility.hours}</strong>
        </div>
      </div>

      <button
        type="button"
        className="route-button"
        disabled={routeLoading}
        onClick={onRouteRequest}
        >
        {routeLoading ? '도보 경로 계산 중…' : '도보 경로 보기'}
        <Icon name="arrow" size={18} />
        </button>

        <div aria-live="polite">
        {walkingRoute && (
            <div className="route-summary">
            <div>
                <span>예상 보행시간</span>
                <strong>
                {Math.max(1, Math.ceil(walkingRoute.durationSec / 60))}분
                </strong>
            </div>

            <div>
                <span>보행거리</span>
                <strong>
                {walkingRoute.distanceM >= 1000
                    ? `${(walkingRoute.distanceM / 1000).toFixed(1)}km`
                    : `${Math.round(walkingRoute.distanceM)}m`}
                </strong>
            </div>
            </div>
        )}

        {routeError && (
            <p className="route-error">{routeError}</p>
        )}
        </div>

        {facility.type === 'emergency_room' && (
        <p className="detail-notice">
            도보 경로입니다. 응급환자 이송 경로나 수용 가능 여부를
            판단하는 정보가 아닙니다.
        </p>
        )}
    </section>
  )
}