"""Read-only post-migration SDK check; accepts an empty database, never imports data."""

try:
    from .supabase_rest import create_supabase_client
except ImportError:
    from supabase_rest import create_supabase_client


def error_category(error):
    code = str(getattr(error, "code", ""))
    # Inspect internally, never print raw errors which can contain connection details.
    message = str(error).lower()
    if code in {"PGRST205", "42P01"} or "could not find the table" in message:
        return "table_missing_or_schema_cache"
    if code in {"PGRST202", "42883"}:
        return "function_missing_or_schema_cache"
    if code == "42501" or "permission denied" in message:
        return "permission_denied"
    if code in {"PGRST301", "PGRST302", "PGRST303", "401"} or "invalid api key" in message:
        return "authentication_failed"
    if any(word in type(error).__name__.lower() for word in ("connect", "network", "timeout", "proxy")):
        return "network_error"
    return "unclassified_api_error"


def main():
    try:
        client = create_supabase_client()
    except Exception:
        print("configuration: failed; credentials hidden")
        return 1
    failed = False
    for table in ("facilities", "facility_access_hours"):
        try:
            response = client.table(table).select("*", count="exact", head=True).execute()
            if not isinstance(response.count, int):
                raise ValueError("Missing exact count")
            print(f"{table}: readable; exact_count={response.count}")
        except Exception as error:
            print(f"{table}: failed; category={error_category(error)}")
            failed = True
    try:
        response = client.table("facilities").select("id", count="exact", head=True).eq(
            "facility_type", "aed"
        ).execute()
        if not isinstance(response.count, int):
            raise ValueError("Missing exact count")
        print(f"aed_exact_count: {response.count}")
    except Exception as error:
        print(f"aed_exact_count: unverified; category={error_category(error)}")
        failed = True
    for name, params, expected in (
        ("get_aed_import_stats", {}, dict),
        ("nearby_facilities", {"p_latitude": 37.5665, "p_longitude": 126.9780,
                               "p_facility_type": "aed", "p_radius_m": 3000}, list),
    ):
        try:
            response = client.rpc(name, params).execute()
            if not isinstance(response.data, expected):
                raise ValueError("Unexpected RPC result")
            print(f"{name}: readable; response_type_valid=true")
        except Exception as error:
            print(f"{name}: failed; category={error_category(error)}")
            failed = True
    print("schema_sdk_check: " + ("incomplete" if failed else "passed"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
