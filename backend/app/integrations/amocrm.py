"""amoCRM REST API v4 client with OAuth2 token management and rate limiting."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import psycopg
from psycopg.rows import dict_row

from app.config import get_settings

logger = logging.getLogger("amocrm")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AmoCRMContact:
    id: int
    name: str
    phone: str | None = None
    telegram_id: str | None = None
    raw: dict = field(default_factory=dict, repr=False)


@dataclass
class AmoCRMLead:
    id: int
    name: str
    pipeline_id: int
    status_id: int
    price: int | None = None
    contact_id: int | None = None
    product_name: str | None = None
    amount: int | None = None
    raw: dict = field(default_factory=dict, repr=False)


# ---------------------------------------------------------------------------
# Token storage (PostgreSQL)
# ---------------------------------------------------------------------------

class TokenStore:
    """Reads/writes amoCRM OAuth tokens from amocrm_tokens table."""

    ACCOUNT_ID = "default"

    def __init__(self, database_url: str) -> None:
        self._dsn = database_url

    def _connect(self):
        return psycopg.connect(self._dsn, row_factory=dict_row)

    def get_tokens(self) -> dict | None:
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT access_token, refresh_token, expires_at "
                    "FROM amocrm_tokens WHERE account_id = %s",
                    (self.ACCOUNT_ID,),
                )
                return cur.fetchone()
        except (psycopg.Error, OSError):
            logger.exception("Failed to read amoCRM tokens")
            return None

    def save_tokens(self, access_token: str, refresh_token: str, expires_in: int) -> None:
        expires_at = datetime.now(tz=timezone.utc) + timedelta(seconds=expires_in)
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO amocrm_tokens (account_id, access_token, refresh_token, expires_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (account_id) DO UPDATE
                    SET access_token  = EXCLUDED.access_token,
                        refresh_token = EXCLUDED.refresh_token,
                        expires_at    = EXCLUDED.expires_at
                    """,
                    (self.ACCOUNT_ID, access_token, refresh_token, expires_at),
                )
                conn.commit()
        except (psycopg.Error, OSError):
            logger.exception("Failed to save amoCRM tokens")

    def delete_tokens(self) -> None:
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute("DELETE FROM amocrm_tokens WHERE account_id = %s", (self.ACCOUNT_ID,))
                conn.commit()
        except (psycopg.Error, OSError):
            logger.exception("Failed to delete amoCRM tokens")


# ---------------------------------------------------------------------------
# Main client
# ---------------------------------------------------------------------------

class AmoCRMClient:
    """
    Synchronous amoCRM REST API v4 client.

    - Rate limiting: 150 ms between requests (~7 req/s).
    - Auto-refresh on 401.
    - Returns None / empty list on any error (graceful degradation).
    """

    REQUEST_DELAY_S = 0.15

    def __init__(self) -> None:
        self._settings = get_settings()
        self._base_url = self._settings.amocrm_base_url
        self._token_store: TokenStore | None = (
            TokenStore(self._settings.database_url) if self._settings.database_url else None
        )
        self._last_request_time: float = 0.0
        self._http = httpx.Client(timeout=15.0)

    # ---- helpers ----------------------------------------------------------

    def _is_configured(self) -> bool:
        return self._settings.amocrm_configured and self._token_store is not None

    def _rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self.REQUEST_DELAY_S:
            time.sleep(self.REQUEST_DELAY_S - elapsed)
        self._last_request_time = time.monotonic()

    # ---- token management -------------------------------------------------

    def _get_access_token(self) -> str | None:
        if not self._token_store:
            return None
        tokens = self._token_store.get_tokens()
        if not tokens:
            return None

        expires_at = tokens["expires_at"]
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at)
        if not expires_at.tzinfo:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if expires_at - datetime.now(tz=timezone.utc) < timedelta(minutes=5):
            logger.info("amoCRM token expiring, refreshing...")
            return self._refresh_token(tokens["refresh_token"])

        return tokens["access_token"]

    def _refresh_token(self, refresh_token: str) -> str | None:
        url = f"https://{self._settings.amocrm_subdomain}.amocrm.ru/oauth2/access_token"
        try:
            resp = self._http.post(url, json={
                "client_id": self._settings.amocrm_client_id,
                "client_secret": self._settings.amocrm_client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "redirect_uri": self._settings.amocrm_redirect_uri,
            })
            if not resp.is_success:
                logger.error("Token refresh failed: %d %s", resp.status_code, resp.text[:300])
                if resp.status_code in (400, 401):
                    self._token_store.delete_tokens()
                return None
            data = resp.json()
            self._token_store.save_tokens(data["access_token"], data["refresh_token"], data["expires_in"])
            logger.info("amoCRM tokens refreshed")
            return data["access_token"]
        except Exception:
            logger.exception("Token refresh error")
            return None

    def exchange_code(self, authorization_code: str) -> bool:
        """Exchange OAuth authorization code for tokens (called from callback)."""
        url = f"https://{self._settings.amocrm_subdomain}.amocrm.ru/oauth2/access_token"
        try:
            resp = self._http.post(url, json={
                "client_id": self._settings.amocrm_client_id,
                "client_secret": self._settings.amocrm_client_secret,
                "grant_type": "authorization_code",
                "code": authorization_code,
                "redirect_uri": self._settings.amocrm_redirect_uri,
            })
            if not resp.is_success:
                logger.error("Code exchange failed: %d", resp.status_code)
                return False
            data = resp.json()
            self._token_store.save_tokens(data["access_token"], data["refresh_token"], data["expires_in"])
            return True
        except Exception:
            logger.exception("Code exchange error")
            return False

    # ---- low-level request ------------------------------------------------

    def _request(
        self,
        method: str,
        endpoint: str,
        body: Any = None,
        *,
        params: dict[str, Any] | None = None,
        retry_on_401: bool = True,
    ) -> dict | None:
        if not self._is_configured():
            return None

        token = self._get_access_token()
        if not token:
            logger.warning("No valid amoCRM access token")
            return None

        self._rate_limit()

        url = f"{self._base_url}{endpoint}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        try:
            resp = self._http.request(method, url, headers=headers, json=body, params=params)
        except httpx.HTTPError:
            logger.exception("HTTP error: %s %s", method, endpoint)
            return None

        if resp.status_code == 401 and retry_on_401:
            logger.info("401 — refreshing token and retrying")
            tokens = self._token_store.get_tokens()
            if tokens:
                self._refresh_token(tokens["refresh_token"])
            return self._request(method, endpoint, body, params=params, retry_on_401=False)

        if resp.status_code == 204:
            return None

        if not resp.is_success:
            logger.error("API error: %s %s → %d: %s", method, endpoint, resp.status_code, resp.text[:500])
            return None

        if not resp.text:
            return None

        try:
            return resp.json()
        except Exception:
            return None

    # ---- contacts ---------------------------------------------------------

    def find_contact_by_phone(self, phone: str) -> AmoCRMContact | None:
        data = self._request("GET", "/contacts", params={"query": phone})
        contacts = (data or {}).get("_embedded", {}).get("contacts", [])
        return self._parse_contact(contacts[0]) if contacts else None

    def find_contact_by_telegram_id(self, telegram_id: str | int) -> AmoCRMContact | None:
        fid = self._settings.amocrm_telegram_id_field
        data = self._request(
            "GET", "/contacts",
            params={f"filter[custom_fields_values][{fid}]": str(telegram_id)},
        )
        contacts = (data or {}).get("_embedded", {}).get("contacts", [])
        return self._parse_contact(contacts[0]) if contacts else None

    def create_contact(
        self, name: str, phone: str | None = None, telegram_id: str | None = None,
    ) -> AmoCRMContact | None:
        fields: list[dict] = []
        if phone:
            fields.append({"field_code": "PHONE", "values": [{"value": phone, "enum_code": "WORK"}]})
        if telegram_id:
            fields.append({
                "field_id": self._settings.amocrm_telegram_id_field,
                "values": [{"value": str(telegram_id)}],
            })
        payload = [{"name": name or "Клиент EdPalm", "custom_fields_values": fields or None}]
        data = self._request("POST", "/contacts", payload)
        contacts = (data or {}).get("_embedded", {}).get("contacts", [])
        if contacts:
            logger.info("Contact created: %d", contacts[0].get("id"))
            return self._parse_contact(contacts[0])
        return None

    def find_or_create_contact(
        self, phone: str | None, name: str | None, telegram_id: str | None,
    ) -> tuple[AmoCRMContact | None, bool]:
        """Return (contact, is_new). Search by telegram_id first, then phone."""
        if telegram_id:
            c = self.find_contact_by_telegram_id(telegram_id)
            if c:
                return c, False
        if phone:
            c = self.find_contact_by_phone(phone)
            if c:
                return c, False
        c = self.create_contact(name=name, phone=phone, telegram_id=telegram_id)
        return c, True

    def _parse_contact(self, raw: dict) -> AmoCRMContact:
        phone = None
        telegram_id = None
        for cf in raw.get("custom_fields_values") or []:
            if cf.get("field_code") == "PHONE":
                phone = (cf.get("values") or [{}])[0].get("value")
            if cf.get("field_id") == self._settings.amocrm_telegram_id_field:
                telegram_id = (cf.get("values") or [{}])[0].get("value")
        return AmoCRMContact(
            id=raw["id"], name=raw.get("name", ""),
            phone=phone, telegram_id=telegram_id, raw=raw,
        )

    # ---- leads ------------------------------------------------------------

    def get_lead(self, lead_id: int) -> AmoCRMLead | None:
        data = self._request("GET", f"/leads/{lead_id}", params={"with": "contacts,custom_fields_values"})
        return self._parse_lead(data) if data and "id" in data else None

    def find_leads_by_contact(self, contact_id: int) -> list[AmoCRMLead]:
        data = self._request(
            "GET", "/leads",
            params={"filter[contacts]": str(contact_id), "with": "contacts,custom_fields_values"},
        )
        leads = (data or {}).get("_embedded", {}).get("leads", [])
        return [self._parse_lead(l) for l in leads]

    def find_active_lead(self, contact_id: int, pipeline_id: int | None = None) -> AmoCRMLead | None:
        pid = pipeline_id or self._settings.amocrm_sales_pipeline_id
        data = self._request(
            "GET", "/leads",
            params={
                "filter[contacts]": str(contact_id),
                "filter[pipeline_id]": str(pid),
                "with": "contacts,custom_fields_values",
            },
        )
        leads = (data or {}).get("_embedded", {}).get("leads", [])
        active = [l for l in leads if l.get("status_id") not in (142, 143)]
        return self._parse_lead(active[0]) if active else None

    def create_lead(
        self,
        name: str,
        contact_id: int,
        pipeline_id: int | None = None,
        product: str | None = None,
        amount: int | None = None,
    ) -> AmoCRMLead | None:
        pid = pipeline_id or self._settings.amocrm_sales_pipeline_id
        fields: list[dict] = []
        if product:
            fields.append({"field_id": self._settings.amocrm_product_field, "values": [{"value": product}]})
        if amount:
            fields.append({"field_id": self._settings.amocrm_amount_field, "values": [{"value": str(amount)}]})
        payload = [{
            "name": name,
            "pipeline_id": pid,
            "price": amount,
            "custom_fields_values": fields or None,
            "_embedded": {"contacts": [{"id": contact_id}]},
        }]
        data = self._request("POST", "/leads", payload)
        leads = (data or {}).get("_embedded", {}).get("leads", [])
        if leads:
            logger.info("Lead created: %d for contact %d", leads[0].get("id"), contact_id)
            return self._parse_lead(leads[0])
        return None

    def update_lead(
        self,
        lead_id: int,
        status_id: int | None = None,
        product: str | None = None,
        amount: int | None = None,
    ) -> AmoCRMLead | None:
        body: dict[str, Any] = {"id": lead_id}
        if status_id is not None:
            body["status_id"] = status_id
        if amount is not None:
            body["price"] = amount
        fields: list[dict] = []
        if product:
            fields.append({"field_id": self._settings.amocrm_product_field, "values": [{"value": product}]})
        if amount is not None:
            fields.append({"field_id": self._settings.amocrm_amount_field, "values": [{"value": str(amount)}]})
        if fields:
            body["custom_fields_values"] = fields
        data = self._request("PATCH", "/leads", [body])
        leads = (data or {}).get("_embedded", {}).get("leads", [])
        return self._parse_lead(leads[0]) if leads else None

    def add_note(self, lead_id: int, text: str) -> bool:
        payload = [{"entity_id": lead_id, "note_type": "common", "params": {"text": text}}]
        data = self._request("POST", "/leads/notes", payload)
        return data is not None

    def _parse_lead(self, raw: dict) -> AmoCRMLead:
        product_name = None
        amount = None
        for cf in raw.get("custom_fields_values") or []:
            if cf.get("field_id") == self._settings.amocrm_product_field:
                product_name = (cf.get("values") or [{}])[0].get("value")
            if cf.get("field_id") == self._settings.amocrm_amount_field:
                v = (cf.get("values") or [{}])[0].get("value")
                if v:
                    try:
                        amount = int(v)
                    except (ValueError, TypeError):
                        pass
        contact_id = None
        embedded_contacts = (raw.get("_embedded") or {}).get("contacts", [])
        if embedded_contacts:
            contact_id = embedded_contacts[0].get("id")
        return AmoCRMLead(
            id=raw.get("id", 0),
            name=raw.get("name", ""),
            pipeline_id=raw.get("pipeline_id", 0),
            status_id=raw.get("status_id", 0),
            price=raw.get("price"),
            contact_id=contact_id,
            product_name=product_name,
            amount=amount,
            raw=raw,
        )
