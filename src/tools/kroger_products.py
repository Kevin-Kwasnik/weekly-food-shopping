from strands import tool
import requests
from utils.kroger_helper import get_kroger_token

CERT_BASE = "https://api-ce.kroger.com/v1"  # Certification/sandbox

@tool
def search_kroger_products(search_term: str, location_id: str = "") -> str:
    """
    Search Kroger products in certification env (sandbox).
    Input: term like "chicken breast" or "rice".
    Optional: location_id (8-digit, e.g., from /locations endpoint).
    Returns top matches with name, price, UPC for mom shopping list.
    """
    token = get_kroger_token()
    url = f"{CERT_BASE}/products"
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "filter.term": search_term,
        "filter.limit": 5  # small for demo
    }
    if location_id:
        params["filter.locationId"] = location_id

    resp = requests.get(url, headers=headers, params=params)
    if resp.status_code == 200:
        data = resp.json().get("data", [])
        if not data:
            return "No products found in certification catalog."
        results = []
        for item in data:
            desc = item.get("description", "N/A")
            upc = item.get("upc", "N/A")
            price = item.get("items", [{}])[0].get("price", {}).get("regular", "N/A")
            results.append(f"{desc} - UPC: {upc} - ${price}")
        return "\n".join(results)
    return f"Error {resp.status_code}: {resp.text[:150]} (check token/scopes?)"