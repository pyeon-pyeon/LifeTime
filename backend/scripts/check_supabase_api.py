"""Read-only Supabase REST connectivity check; never prints API credentials."""

try:
    from .supabase_rest import create_supabase_client
except ImportError:
    from supabase_rest import create_supabase_client


def main():
    try:
        client = create_supabase_client()
        # Check the actual application table rather than unrelated Storage grants.
        client.table("facilities").select("id").limit(1).execute()
        print("Supabase REST API connection succeeded for the configured project.")
        return 0
    except Exception as error:  # noqa: BLE001 - SDK details can contain credentials
        print(f"Supabase REST API connection failed ({type(error).__name__}); details hidden.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
