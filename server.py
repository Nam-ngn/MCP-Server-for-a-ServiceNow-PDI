import os

import httpx
from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()

mcp = FastMCP("ServiceNow PDI")

INSTANCE_URL = os.environ.get("SERVICENOW_INSTANCE_URL", "").rstrip("/")
USER = os.environ.get("SERVICENOW_USER", "")
PWD = os.environ.get("SERVICENOW_PASSWORD", "")

MAX_LIMIT = 1000
VALID_DISPLAY_VALUES = {"true", "false", "all"}


def _require_settings() -> None:
    missing = [
        name
        for name, value in (
            ("SERVICENOW_INSTANCE_URL", INSTANCE_URL),
            ("SERVICENOW_USER", USER),
            ("SERVICENOW_PASSWORD", PWD),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Missing ServiceNow settings: " + ", ".join(missing)
        )


async def _request(method: str, path: str, **kwargs) -> dict:
    _require_settings()
    async with httpx.AsyncClient(auth=(USER, PWD), timeout=30.0) as client:
        try:
            response = await client.request(method, f"{INSTANCE_URL}{path}", **kwargs)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text
            try:
                detail = exc.response.json().get("error", {}).get("message", detail)
            except ValueError:
                pass
            raise RuntimeError(
                f"ServiceNow a répondu {exc.response.status_code} sur {path} : {detail}"
            ) from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"Impossible de joindre {INSTANCE_URL} : {exc}") from exc
        if not response.content:
            return {}
        return response.json()


@mcp.tool()
async def query_table(
    table: str,
    query: str = "",
    fields: str = "",
    limit: int = 20,
    offset: int = 0,
    display_value: str = "true",
) -> dict:
    """Interroge une table ServiceNow via la Table API (lecture seule).

    - table : nom technique de la table (ex: incident, sys_user)
    - query : encoded query ServiceNow (ex: active=true^priority=1)
    - fields : liste de champs séparés par des virgules (vide = tous)
    - limit : nombre max de résultats (borné à 1000)
    - offset : décalage pour la pagination
    - display_value : "true" (valeurs affichées), "false" (valeurs brutes/sys_id) ou "all" (les deux)
    """
    if display_value not in VALID_DISPLAY_VALUES:
        raise ValueError(f"display_value doit être l'un de {sorted(VALID_DISPLAY_VALUES)}")
    limit = max(1, min(limit, MAX_LIMIT))
    offset = max(0, offset)
    return await _request(
        "GET",
        f"/api/now/table/{table}",
        params={
            "sysparm_query": query,
            "sysparm_fields": fields,
            "sysparm_limit": limit,
            "sysparm_offset": offset,
            "sysparm_display_value": display_value,
        },
    )


@mcp.tool()
async def create_record(table: str, fields: dict) -> dict:
    """Crée un enregistrement dans une table ServiceNow.

    - table : nom technique de la table (ex: incident)
    - fields : dictionnaire des champs à renseigner (ex: {"short_description": "..."})
    """
    if not fields:
        raise ValueError("fields ne peut pas être vide")
    return await _request("POST", f"/api/now/table/{table}", json=fields)


@mcp.tool()
async def update_record(table: str, fields: dict, sys_id: str = "", query: str = "") -> dict:
    """Met à jour un enregistrement existant dans une table ServiceNow.

    - table : nom technique de la table (ex: incident)
    - fields : dictionnaire des champs à mettre à jour
    - sys_id : identifiant de l'enregistrement à modifier (si connu)
    - query : encoded query pour retrouver l'enregistrement si le sys_id n'est pas connu
      (ex: "number=INC0010002"). Doit désigner un seul enregistrement.

    Fournir sys_id OU query.
    """
    if not fields:
        raise ValueError("fields ne peut pas être vide")
    if not sys_id and not query:
        raise ValueError("Fournir sys_id ou query")
    if not sys_id:
        found = await _request(
            "GET",
            f"/api/now/table/{table}",
            params={"sysparm_query": query, "sysparm_fields": "sys_id", "sysparm_limit": 2},
        )
        records = found.get("result", [])
        if not records:
            raise RuntimeError(f"Aucun enregistrement trouvé pour la requête '{query}' sur {table}")
        if len(records) > 1:
            raise RuntimeError(
                f"Plusieurs enregistrements trouvés pour la requête '{query}' sur {table} : préciser sys_id"
            )
        sys_id = records[0]["sys_id"]
    return await _request("PATCH", f"/api/now/table/{table}/{sys_id}", json=fields)


if __name__ == "__main__":
    _require_settings()
    mcp.run()
