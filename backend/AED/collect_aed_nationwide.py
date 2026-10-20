
import json
import math
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from parse_aed import get_value, parse_schedule

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR.parent / ".env")

API_URL = (
    "https://apis.data.go.kr/B552657/"
    "AEDInfoInqireService/getAedFullDown"
)
API_KEY = os.getenv("AED_API_KEY")

PAGE_SIZE = 100
OUTPUT_FILE = BASE_DIR / "aed_nationwide.json"
PROGRESS_FILE = BASE_DIR / "aed_collection_progress.json"


def fetch_page(session, page_no):
    for attempt in range(1, 4):
        try:
            response = session.get(
                API_URL,
                params={
                    "serviceKey": API_KEY,
                    "pageNo": page_no,
                    "numOfRows": PAGE_SIZE,
                },
                timeout=60,
            )
            response.raise_for_status()

            root = ET.fromstring(response.content)
            code = root.findtext("./header/resultCode")

            if code != "00":
                message = root.findtext("./header/resultMsg")
                raise RuntimeError(
                    f"API 오류: {code} / {message}"
                )

            items = root.findall("./body/items/item")
            total = root.findtext("./body/totalCount")

            return items, int(total) if total else None

        except (
            requests.RequestException,
            ET.ParseError,
        ) as error:
            print(
                f"페이지 {page_no} 재시도 "
                f"{attempt}/3: {type(error).__name__}"
            )
            if attempt == 3:
                raise
            time.sleep(attempt * 2)


def convert_item(item, collected_at):
    source_id = get_value(item, "serialSeq")
    lat_raw = get_value(item, "wgs84Lat")
    lon_raw = get_value(item, "wgs84Lon")

    if not source_id or not lat_raw or not lon_raw:
        return None

    try:
        latitude = float(lat_raw)
        longitude = float(lon_raw)
    except ValueError:
        return None

    if not (
        -90 <= latitude <= 90
        and -180 <= longitude <= 180
    ):
        return None

    schedule_status, access_hours = parse_schedule(item)

    sido = get_value(item, "sido")
    gugun = get_value(item, "gugun")
    address = get_value(item, "buildAddress")

    full_address = " ".join(
        part for part in [sido, gugun, address] if part
    ) or None

    return {
        "facility_type": "aed",
        "source_id": source_id,
        "name": get_value(item, "org"),
        "address": full_address,
        "sido": sido,
        "gugun": gugun,
        "latitude": latitude,
        "longitude": longitude,
        "installation_detail": get_value(item, "buildPlace"),
        "contact_phone": get_value(item, "clerkTel"),
        "schedule_status": schedule_status,
        "access_hours": access_hours,
        "source_name": "국립중앙의료원",
        "source_updated_at": None,
        "data_collected_at": collected_at,
    }


def save_progress(next_page, facilities):
    temp_file = PROGRESS_FILE.with_suffix(".tmp")
    temp_file.write_text(
        json.dumps(
            {
                "next_page": next_page,
                "facilities": facilities,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    temp_file.replace(PROGRESS_FILE)


def main():
    if not API_KEY:
        raise RuntimeError("AED_API_KEY가 없습니다.")

    collected_at = datetime.now(
        timezone.utc
    ).isoformat()

    facilities = {}
    start_page = 1

    if PROGRESS_FILE.exists():
        progress = json.loads(
            PROGRESS_FILE.read_text(encoding="utf-8")
        )
        start_page = progress["next_page"]
        facilities = progress["facilities"]
        print(f"이전 작업 복구: {start_page}페이지부터")

    with requests.Session() as session:
        page = start_page
        total_pages = None

        while True:
            items, total_count = fetch_page(session, page)

            if total_count is not None:
                total_pages = math.ceil(
                    total_count / PAGE_SIZE
                )

            if not items:
                if total_pages is not None and page <= total_pages:
                    raise RuntimeError(
                        f"예상보다 일찍 빈 페이지가 반환됨: {page}"
                    )
                break

            for item in items:
                facility = convert_item(
                    item, collected_at
                )
                if facility:
                    facilities[facility["source_id"]] = facility

            print(
                f"[{page}/{total_pages or '?'}] "
                f"누적 유효 AED: {len(facilities)}건"
            )

            save_progress(page + 1, facilities)

            if total_pages is not None and page >= total_pages:
                break

            if total_pages is None and len(items) < PAGE_SIZE:
                break

            page += 1
            time.sleep(0.2)

    OUTPUT_FILE.write_text(
        json.dumps(
            list(facilities.values()),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\n전국 AED 수집 완료")
    print("유효 AED:", len(facilities))
    print("저장 파일:", OUTPUT_FILE)

    if PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()



if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit(f"AED collection failed ({type(error).__name__}); credentials hidden") from None
