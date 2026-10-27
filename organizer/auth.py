"""
auth.py - Microsoft Graph authentication to read an Outlook / Microsoft 365 mailbox.

Strategy:
  - DELEGATED permission (Mail.Read): reads only YOUR mailbox, acting as you.
  - "Device code" flow: you type a short code in the browser ONCE.
  - Disk cache: the refresh token is saved, so the next runs renew silently.

What your IT team provides (Azure / Entra ID app registration):
  - Application (client) ID  -> GRAPH_CLIENT_ID in .env
  - Directory (tenant) ID    -> GRAPH_TENANT_ID in .env
  - Single-tenant app, delegated Mail.Read permission with admin consent.
  - "Allow public client flows" = Yes (required for the device code flow).

SECURITY: token_cache.bin holds a refresh token. Treat it like a password:
it is listed in .gitignore and must never be shared.
"""

import atexit
import os
import sys

try:  # use the Windows certificate store (helps behind corporate proxies)
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

CLIENT_ID = os.environ.get("GRAPH_CLIENT_ID", "")
TENANT_ID = os.environ.get("GRAPH_TENANT_ID", "")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"

# Least privilege: read-only mail access. MSAL adds openid/profile/offline_access itself.
SCOPES = ["Mail.Read"]
CACHE_FILE = "token_cache.bin"


def _load_cache(msal):
    """Loads the token cache from disk and saves it again on exit if it changed."""
    cache = msal.SerializableTokenCache()
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache.deserialize(f.read())

    def _save():
        if cache.has_state_changed:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                f.write(cache.serialize())

    atexit.register(_save)
    return cache


def get_token() -> str:
    """Returns a valid Microsoft Graph access token (silent first, device code if needed)."""
    if not CLIENT_ID or not TENANT_ID:
        raise RuntimeError("Set GRAPH_CLIENT_ID and GRAPH_TENANT_ID in your .env file "
                           "(see .env.example).")
    import msal

    cache = _load_cache(msal)
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=cache)

    # 1) Happy path: a cached refresh token still works.
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            return result["access_token"]

    # 2) First run (or expired cache): device code flow.
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise RuntimeError("Could not start the device flow. Check that 'Allow public "
                           f"client flows' is enabled. Detail: {flow.get('error_description', flow)}")
    print(flow["message"])          # "Open https://microsoft.com/devicelogin and enter ABC123"
    sys.stdout.flush()

    result = app.acquire_token_by_device_flow(flow)   # waits until you finish the login
    if "access_token" not in result:
        raise RuntimeError(f"Could not get a token: {result.get('error')} - "
                           f"{result.get('error_description')}")
    return result["access_token"]


if __name__ == "__main__":
    token = get_token()
    print("\nAuthentication OK.")
