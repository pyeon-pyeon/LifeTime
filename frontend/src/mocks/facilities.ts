import type { Facility } from '../types/facility'

export const mockFacilities: Facility[] = [
  {
    id: 'demo-aed-1',
    type: 'aed',
    name: '가상 중앙주민센터',
    address: '서울시청 주변 시연용 좌표',
    detail: '1층 안내데스크 옆 · 가상 정보',
    hours: '평일 09:00–18:00 · 가상 정보',
    latitude: 37.5665,
    longitude: 126.978,
  },
  {
    id: 'demo-aed-2',
    type: 'aed',
    name: '가상 시민도서관',
    address: '서울시청 주변 시연용 좌표',
    detail: '1층 로비 출입구 · 가상 정보',
    hours: '매일 09:00–22:00 · 가상 정보',
    latitude: 37.5682,
    longitude: 126.9755,
  },
  {
    id: 'demo-er-1',
    type: 'emergency_room',
    name: '가상 중앙병원 응급실',
    address: '서울시청 주변 시연용 좌표',
    detail: '본관 응급실 출입구 · 가상 정보',
    hours: '운영·수용 여부 확인 필요',
    latitude: 37.5643,
    longitude: 126.9805,
  },
]