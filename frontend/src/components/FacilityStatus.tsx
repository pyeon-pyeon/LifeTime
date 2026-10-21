import type { FacilityLoadStatus } from '../hooks/useNearbyFacilities'
import Icon from './Icon'

type Props = {
  status: FacilityLoadStatus
  error: string | null
  onRetry: () => void
}

export default function FacilityStatus({
  status,
  error,
  onRetry,
}: Props) {
  if (status === 'loading') {
    return (
      <div className="empty-results" role="status">
        <Icon name="search" size={28} />
        <h3>주변 시설을 찾고 있어요</h3>
        <p>공공데이터 기반 시설정보를 조회하고 있습니다.</p>
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="empty-results" role="alert">
        <h3>시설을 불러오지 못했어요</h3>
        <p>{error ?? '서버 연결을 확인해 주세요.'}</p>

        <button
          type="button"
          className="facility-retry-button"
          onClick={onRetry}
        >
          다시 시도
        </button>
      </div>
    )
  }

  if (status === 'idle') {
    return (
      <div className="empty-results" role="status">
        <Icon name="location" size={28} />
        <h3>검색 위치를 설정해 주세요</h3>
        <p>현재 위치를 허용하거나 지도에서 위치를 수정해 주세요.</p>
      </div>
    )
  }

  return (
    <div className="empty-results" role="status">
      <Icon name="search" size={28} />
      <h3>조회된 시설이 없어요</h3>
      <p>
        검색 위치와 조건을 확인해 주세요.
        현재 데이터 적재 준비 중으로 결과가 없을 수 있습니다.
      </p>
    </div>
  )
}