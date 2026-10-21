export type WalkingRoute = {
  distanceM: number
  durationSec: number

  // 단계별 경로. 서로 다른 단계를 임의의 직선으로 연결하지 않음.
  segments: [number, number][][]
}