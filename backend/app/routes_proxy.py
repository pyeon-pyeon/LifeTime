"""Proxy Kakao route requests without exposing the REST API key."""

import os
from typing import Literal

import httpx
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

router = APIRouter()


async def request_route(
    mode: Literal["walking", "driving"],
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
):
    headers = {"Cache-Control": "no-store"}

    def error(status: int, message: str):
        return JSONResponse(
            status_code=status,
            content={"message": message},
            headers=headers,
        )

    api_key = os.getenv("KAKAO_REST_API_KEY", "").strip()

    if not api_key:
        return error(503, "서버에 KAKAO_REST_API_KEY가 설정되지 않았습니다.")

    if mode == "driving":
        url = "https://apis-navi.kakaomobility.com/v1/directions"
        params = {
            "origin": f"{start_x},{start_y}",
            "destination": f"{end_x},{end_y}",
            "priority": "TIME",
            "summary": "false",
            "alternatives": "false",
        }
    else:
        url = "https://dapi.kakao.com/v2/routing/walk"
        params = {
            "start_x": str(start_x),
            "start_y": str(start_y),
            "end_x": str(end_x),
            "end_y": str(end_y),
            "input_coord": "WGS84",
            "output_coord": "WGS84",
        }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                url,
                params=params,
                headers={"Authorization": f"KakaoAK {api_key}"},
            )
    except httpx.TimeoutException:
        return error(504, "경로 서버 응답 시간이 초과됐습니다.")
    except httpx.RequestError:
        return error(502, "경로 서버에 연결하지 못했습니다.")

    if response.status_code == 429:
        return error(429, "경로 API 호출 제한에 도달했습니다.")

    if not response.is_success:
        return error(
            502,
            f"카카오 경로 요청 실패 ({response.status_code}). "
            "REST 키·사용 권한·쿼터를 확인해 주세요.",
        )

    try:
        body = response.json()
    except ValueError:
        return error(502, "경로 서버의 응답 형식이 올바르지 않습니다.")

    if not isinstance(body, dict):
        return error(502, "경로 서버의 응답 형식이 올바르지 않습니다.")

    return JSONResponse(content=body, headers=headers)


@router.get("/api/dev/walking-route")
async def walking_route(
    start_x: float = Query(ge=-180, le=180, allow_inf_nan=False),
    start_y: float = Query(ge=-90, le=90, allow_inf_nan=False),
    end_x: float = Query(ge=-180, le=180, allow_inf_nan=False),
    end_y: float = Query(ge=-90, le=90, allow_inf_nan=False),
):
    return await request_route(
        "walking", start_x, start_y, end_x, end_y,
    )


@router.get("/api/dev/driving-route")
async def driving_route(
    start_x: float = Query(ge=-180, le=180, allow_inf_nan=False),
    start_y: float = Query(ge=-90, le=90, allow_inf_nan=False),
    end_x: float = Query(ge=-180, le=180, allow_inf_nan=False),
    end_y: float = Query(ge=-90, le=90, allow_inf_nan=False),
):
    return await request_route(
        "driving", start_x, start_y, end_x, end_y,
    )