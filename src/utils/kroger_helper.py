import os
import requests
from typing import Optional

def get_kroger_token(
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> str:
    """
    Fetch Kroger Bearer token using client credentials grant.
    Falls back to .env if args not provided.
    """
    client_id = client_id or os.getenv("KROGER_CLIENT_ID")
    client_secret = client_secret or os.getenv("KROGER_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise ValueError("Missing Kroger client_id or client_secret (check .env or args)")

    url = "https://api-ce.kroger.com/v1/connect/oauth2/token"
    data = {
        "grant_type": "client_credentials",
        "scope": "product.compact"  # add more scopes later if needed
    }

    try:
        resp = requests.post(
            url,
            data=data,
            auth=(client_id, client_secret),
            timeout=10  # prevent hanging
        )
        resp.raise_for_status()  # nicer error than manual check
        token = resp.json()["access_token"]
        
        return token
    except requests.RequestException as e:
        raise ValueError(f"Kroger token request failed: {str(e)}") from e