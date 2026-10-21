import type {
  Facility,
  FacilityFilter,
} from '../types/facility'
import Icon from './Icon'
import FacilityStatus from './FacilityStatus'
import type { FacilityLoadStatus } from '../hooks/useNearbyFacilities'
import type { WalkingRanks } from '../types/ranking'
import { LayoutGrid, HeartPulse, Cross } from 'lucide-react'

type FacilityExplorerProps = {
  facilities: (Facility & { straightDistanceM: number })[]
  filter: FacilityFilter
  query: string
  selectedId: string | null
  loadStatus: FacilityLoadStatus
  loadError: string | null
  walkingRanks: WalkingRanks
  comparisonEnabled: boolean
  comparisonLoading: boolean
  comparisonDone: boolean
  comparisonCompleted: number
  comparisonTotal: number
  comparisonSuccessCount: number
  comparisonFailedCount: number
  routeCooldownSeconds: number
  onCompare: () => void
  onRetry: () => void
  onFilterChange: (filter: FacilityFilter) => void
  onQueryChange: (query: string) => void
  onSelect: (id: string) => void
}

const filters = [
  { value: 'all', label: '전체', icon: LayoutGrid },
  { value: 'aed', label: 'AED', icon: HeartPulse },
  {
    value: 'emergency_room',
    label: '응급실',
    icon: Cross,
  },
] satisfies {
  value: FacilityFilter
  label: string
  icon: typeof LayoutGrid
}[]

export default function FacilityExplorer({
  facilities,
  filter,
  query,
  selectedId,
  loadStatus,
  loadError,
  walkingRanks,
  comparisonEnabled,
  comparisonLoading,
  comparisonDone,
  comparisonCompleted,
  comparisonTotal,
  comparisonSuccessCount,
  comparisonFailedCount,
  routeCooldownSeconds,
  onCompare,
  onRetry,
  onFilterChange,
  onQueryChange,
  onSelect,
}: FacilityExplorerProps) {
  const travelMode = filter === 'emergency_room' ? '차량' : '도보'
  const comparisonDescription =
    filter === 'emergency_room'
      ? '직선거리로 가까운 후보 최대 5곳 중 예상 차량 이동시간이 짧은 3곳을 강조합니다.'
      : '직선거리로 가까운 후보 최대 5곳 중 예상 보행시간이 짧은 3곳을 강조합니다.'
  return (
    <section className="explorer" aria-labelledby="explorer-heading">
      <div className="explorer-intro">

        <p className="eyebrow">NEAR YOU, WHEN IT MATTERS</p>

        <h1 id="explorer-heading">
          필요한 순간,<br />
          가장 가까운 도움.
        </h1>

        <p className="intro-description">
          주변 AED와 응급의료시설을 살펴보세요.
        </p>
      </div>

      <label className="search-box">
        <Icon name="search" />

        <input
          aria-label="시설명 또는 주소 검색"
          placeholder="시설명이나 주소로 검색"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
        />

        {query && (
          <button
            type="button"
            className="clear-search"
            aria-label="검색어 지우기"
            onClick={() => onQueryChange('')}
          >
            <Icon name="close" size={16} />
          </button>
        )}
      </label>

      <div className="filter-row" role="group" aria-label="응급시설 종류 선택">
        {filters.map(({ value, label, icon: TabIcon }) => (
          <button
            key={value}
            type="button"
            className={`filter-button ${value}`}
            aria-pressed={filter === value}
            onClick={() => onFilterChange(value)}
          >
            <TabIcon
              className="filter-tab-icon"
              size={20}
              strokeWidth={2}
              aria-hidden="true"
            />
            <span>{label}</span>
          </button>
        ))}
      </div>
      
      {filter !== 'all' && (
        <div className="walking-comparison">
          <button
            type="button"
            className="walking-compare-button"
            disabled={
              !comparisonEnabled ||
              comparisonLoading ||
              comparisonDone ||
              routeCooldownSeconds > 0
            }
            onClick={onCompare}
          >
            <Icon name="clock" size={16} />

            {routeCooldownSeconds > 0
              ? `요청 대기 ${routeCooldownSeconds}초`
              : comparisonLoading
              ? `경로 비교 중 ${comparisonCompleted}/${comparisonTotal}`
              : comparisonDone
                ? `${travelMode}시간 비교 완료`
                : `${travelMode}시간 비교 · 최대 5곳`}
          </button>

          <p className="walking-compare-note" aria-live="polite">
            {comparisonDone
              ? `${travelMode}시간 비교 성공 ${comparisonSuccessCount}곳 · 경로 확인 불가 ${comparisonFailedCount}곳`
              : comparisonDescription}
          </p>

          {filter === 'emergency_room' && (
            <p className="walking-compare-note">
              차량 이동시간 기준이며 환자 수용 가능 여부는 별도 확인이 필요합니다.
            </p>
          )}
        </div>
      )}

      <div className="list-heading">
        <h2>
          주변 시설 <span>{facilities.length}</span>
        </h2>
        <span>직선거리순</span>
      </div>

      <div
        className="results-scroll"
        aria-busy={loadStatus === 'loading'}
      >
        {loadStatus !== 'success' || facilities.length === 0 ? (
          <FacilityStatus
            status={loadStatus}
            error={loadError}
            onRetry={onRetry}
          />
        ) : (
          <ul className="facility-list">
            {facilities.map((facility) => (
              <li key={facility.id}>
                <button
                  type="button"
                  className={`facility-card ${
                    walkingRanks[facility.id] ? 'is-walking-top' : ''
                  }`}
                  aria-pressed={selectedId === facility.id}
                  onClick={() => onSelect(facility.id)}
                >
                  <div className="card-top">
                    <span className={`facility-category ${facility.type}`}>
                      {facility.type === 'aed'
                        ? '자동심장충격기'
                        : '응급실'}
                    </span>
                    <Icon name="arrow" size={18} />
                  </div>

                  <h3>{facility.name}</h3>
                  {walkingRanks[facility.id] && (
                    <span className="walking-rank-badge">
                      {facility.type === 'aed' ? '도보' : '차량'}
                      {' '}
                      {walkingRanks[facility.id].rank}순위
                      {' · 약 '}
                      {Math.max(
                        1,
                        Math.ceil(walkingRanks[facility.id].durationSec / 60),
                      )}분
                    </span>
                  )}
                  <p className="facility-address">{facility.address}</p>

                  <div className="card-bottom">
                    <span className="time-preview">
                      <Icon name="pin" size={15} />
                      직선거리 {Math.round(facility.straightDistanceM)}m
                    </span>

                    <span>상세 보기</span>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="panel-footer">
        <span className="info-mark">i</span>
        공공데이터 기반 정보로 실제 현장 상황과 다를 수 있습니다.
      </div>
    </section>
  )
}
