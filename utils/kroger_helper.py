import requests

def get_kroger_token(client_id: str, client_secret: str) -> str:
    url = "https://api.kroger.com/v1/connect/oauth2/token"
    data = {
        "grant_type": "client_credentials",
        "scope": "product.compact"
    }
    auth = (client_id, client_secret)
    resp = requests.post(url, data=data, auth=auth)
    if resp.status_code == 200:
        return resp.json()["access_token"]
    raise ValueError(f"Token error: {resp.text}")