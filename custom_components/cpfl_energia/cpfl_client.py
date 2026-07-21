# -*- coding: utf-8 -*-
"""
CPFL Energia Web API client.

This library is synchronous (like the CSG reference) because updates are
infrequent (every few hours) and each update only contains a few requests.

Authentication uses CPFL's Azure B2C-based login flow:
  1. POST credentials to the B2C token endpoint
  2. Exchange the B2C token for a CPFL API token via /api/token
  3. Use the CPFL API token as a Bearer header for all subsequent requests
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import requests

_LOGGER = logging.getLogger(__name__)

# -- API endpoints -----------------------------------------------------------

BASE_URL = "https://servicosonline.cpfl.com.br"
API_BASE = f"{BASE_URL}/agencia-webapp/api"
B2C_LOGIN_URL = "https://www.cpfl.com.br/b2c-auth/login?sistema=agv"

# API paths
PATH_TOKEN = "/token"
PATH_VALIDATE_TOKEN = "/validationToken"
PATH_USER_INSTALLATIONS = "/user/instalacoes"
PATH_INSTALLATION_INFO = "/instalacao/informacoes-instalacao/"
PATH_CONSUMPTION_GRAPHS = "/historico-consumo/busca-graficos"
PATH_INVOICE_HISTORY = "/historico-contas/"
PATH_PAID_INVOICES = "/historico-contas/contas-quitadas"
PATH_PAYMENT_SLIP = "/historico-contas/via-pagamento"
PATH_CONSOLIDATED_ITEMS = "/historico-contas/itens-consolidados"

REQUEST_TIMEOUT = 30

# Response keys
KEY_SUCCESS = "success"
KEY_MESSAGE = "message"
KEY_DATA = "data"
KEY_TOKEN = "token"
KEY_ACCESS_TOKEN = "accessToken"
KEY_INSTALACAO = "instalacao"
KEY_CODIGO = "codigo"
KEY_NOME = "nome"
KEY_ENDERECO = "endereco"
KEY_CONTAS = "contas"
KEY_VALOR = "valor"
KEY_VENCIMENTO = "vencimento"
KEY_REFERENCIA = "referencia"
KEY_CONSUMO = "consumo"
KEY_KWH = "kwh"
KEY_TIPO = "tipo"

# Tariff flag colors in Portuguese
TARIFF_FLAGS = {
    "verde": "Verde",
    "amarela": "Amarela",
    "vermelha": "Vermelha",
    "vermelha2": "Vermelha (Patamar 2)",
}


class CPFLError(Exception):
    """Generic CPFL API error."""


class CPFLHTTPError(CPFLError):
    """Unexpected HTTP status code."""

    def __init__(self, code: int, message: str = "") -> None:
        super().__init__(f"HTTP {code}: {message}")
        self.status_code = code


class InvalidCredentials(CPFLError):
    """Invalid login credentials."""


class NotLoggedIn(CPFLError):
    """Session not authenticated or expired."""


class CPFLAuthExpired(CPFLError):
    """Authentication token expired."""


# -- Data classes ------------------------------------------------------------


@dataclass
class CPFLInstallation:
    """Represents a CPFL electrical installation (Instalação)."""

    installation_number: str
    address: str = ""
    name: str = ""
    company: str = ""
    uc: str = ""  # Unidade Consumidora
    contract: str = ""

    def dump(self) -> dict:
        return {
            "installation_number": self.installation_number,
            "address": self.address,
            "name": self.name,
            "company": self.company,
            "uc": self.uc,
            "contract": self.contract,
        }

    @staticmethod
    def from_dict(data: dict) -> "CPFLInstallation":
        return CPFLInstallation(
            installation_number=str(data.get("installation_number", data.get(KEY_CODIGO, ""))),
            address=data.get("address", data.get(KEY_ENDERECO, "")),
            name=data.get("name", data.get(KEY_NOME, "")),
            company=data.get("company", ""),
            uc=data.get("uc", ""),
            contract=data.get("contract", ""),
        )


@dataclass
class CPFLBill:
    """Represents a single electricity bill (Fatura)."""

    reference_month: str = ""
    due_date: str = ""
    amount: float = 0.0
    consumption_kwh: float = 0.0
    status: str = ""  # "paga" (paid), "aberta" (open), "vencida" (overdue)


@dataclass
class CPFLConsumptionData:
    """Represents consumption data for a period."""

    kwh: float = 0.0
    amount: float = 0.0
    average_daily_kwh: float = 0.0
    days: int = 0
    history: list[dict] = field(default_factory=list)


# -- API Client --------------------------------------------------------------


class CPFLClient:
    """Synchronous CPFL Energia API client."""

    def __init__(self) -> None:
        self._session: requests.Session | None = None
        self._token: str | None = None
        self._document: str = ""
        self._password: str = ""

    # -- Session management --------------------------------------------------

    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Home Assistant; CPFL Energia Integration)",
            })
        return self._session

    def set_authentication(self, token: str) -> None:
        """Set the authentication token."""
        self._token = token
        session = self._get_session()
        session.headers.update({"Authorization": f"Bearer {token}"})

    @staticmethod
    def load(saved_data: dict) -> "CPFLClient":
        """Create a client from saved config data."""
        client = CPFLClient()
        token = saved_data.get("auth_token", "")
        if token:
            client.set_authentication(token)
        return client

    # -- HTTP helpers --------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        json_data: dict | None = None,
        params: dict | None = None,
    ) -> dict | list | None:
        """Make an authenticated API request."""
        if not self._token:
            raise NotLoggedIn("No authentication token")

        url = f"{API_BASE}{path}"
        session = self._get_session()
        _LOGGER.debug("CPFL API %s %s", method, url)

        try:
            resp = session.request(
                method,
                url,
                json=json_data,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as err:
            raise CPFLHTTPError(0, str(err)) from err

        if resp.status_code == 401:
            raise CPFLAuthExpired("Token expired")
        if resp.status_code == 403:
            raise InvalidCredentials("Access denied")
        if resp.status_code != 200:
            raise CPFLHTTPError(resp.status_code, resp.text[:500])

        try:
            return resp.json()
        except ValueError:
            _LOGGER.warning("CPFL API returned non-JSON response from %s", path)
            return None

    # -- Authentication ------------------------------------------------------

    def login(self, document: str, password: str) -> str:
        """Login with CPF/CNPJ and password.

        Returns the API auth token.
        """
        self._document = re.sub(r"\D", "", document)
        self._password = password
        session = self._get_session()

        # Step 1: Get the B2C login page to obtain the token endpoint
        # The CPFL portal uses Azure B2C, but the agencia-webapp API
        # has its own /api/token endpoint that accepts credentials.
        try:
            resp = session.post(
                f"{API_BASE}{PATH_TOKEN}",
                json={
                    "document": self._document,
                    "password": password,
                },
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as err:
            raise CPFLHTTPError(0, str(err)) from err

        if resp.status_code == 401 or resp.status_code == 403:
            raise InvalidCredentials("Invalid document or password")
        if resp.status_code != 200:
            raise CPFLHTTPError(resp.status_code, resp.text[:500])

        data = resp.json()
        token = data.get(KEY_TOKEN) or data.get(KEY_ACCESS_TOKEN) or ""
        if not token:
            # Some responses nest the token under "data"
            inner = data.get(KEY_DATA, {})
            if isinstance(inner, dict):
                token = inner.get(KEY_TOKEN, "")
        if not token:
            raise CPFLError(f"Login succeeded but no token in response: {data}")

        self.set_authentication(token)
        _LOGGER.info("CPFL login successful for document %s", self._document)
        return token

    def verify_login(self) -> bool:
        """Check if the current session is still valid."""
        if not self._token:
            return False
        try:
            self._request("GET", PATH_VALIDATE_TOKEN)
            return True
        except (CPFLAuthExpired, NotLoggedIn):
            return False
        except CPFLError:
            # Other errors may not mean session is invalid
            return False

    # -- Installation data ---------------------------------------------------

    def get_installations(self) -> list[CPFLInstallation]:
        """Get all installations linked to the account."""
        result = self._request("GET", PATH_USER_INSTALLATIONS)
        if result is None:
            return []

        installations: list[CPFLInstallation] = []
        raw_list = result if isinstance(result, list) else result.get("data", [])
        if isinstance(raw_list, list):
            for item in raw_list:
                if isinstance(item, dict):
                    installations.append(CPFLInstallation.from_dict(item))
        return installations

    def get_installation_info(self, installation_number: str) -> dict:
        """Get detailed info about a specific installation."""
        result = self._request(
            "GET", f"{PATH_INSTALLATION_INFO}{installation_number}"
        )
        if result is None:
            return {}
        if isinstance(result, dict):
            return result.get("data", result)
        return {}

    # -- Consumption data ----------------------------------------------------

    def get_consumption_history(
        self,
        installation_number: str,
        months: int = 12,
    ) -> CPFLConsumptionData:
        """Get consumption history for the installation."""
        result = self._request(
            "POST",
            PATH_CONSUMPTION_GRAPHS,
            json_data={
                "instalacao": installation_number,
                "meses": months,
            },
        )
        if result is None:
            return CPFLConsumptionData()

        data = result if isinstance(result, dict) else {}
        history = data.get("data", data) if isinstance(data, dict) else {}

        # Parse monthly consumption entries
        entries: list[dict] = []
        total_kwh = 0.0
        total_amount = 0.0
        monthly_list = history.get("consumos", history.get("listaConsumo", []))
        if isinstance(monthly_list, list):
            for entry in monthly_list:
                if not isinstance(entry, dict):
                    continue
                kwh = float(entry.get(KEY_CONSUMO, entry.get(KEY_KWH, 0)) or 0)
                amount = float(entry.get(KEY_VALOR, 0) or 0)
                entries.append({
                    "month": entry.get("mes", entry.get(KEY_REFERENCIA, "")),
                    "kwh": kwh,
                    "amount": amount,
                })
                total_kwh += kwh
                total_amount += amount

        # Calculate daily average from the most recent month
        avg_daily = 0.0
        days = 0
        if entries:
            latest = entries[0]
            kwh = latest.get("kwh", 0)
            # Assume ~30 days per month
            days = 30
            avg_daily = round(kwh / days, 2) if days else 0

        return CPFLConsumptionData(
            kwh=total_kwh,
            amount=total_amount,
            average_daily_kwh=avg_daily,
            days=days,
            history=entries,
        )

    # -- Billing data --------------------------------------------------------

    def get_invoice_history(
        self,
        installation_number: str,
        months: int = 12,
    ) -> list[CPFLBill]:
        """Get invoice (fatura) history for the installation."""
        result = self._request(
            "GET",
            PATH_INVOICE_HISTORY,
            params={
                "instalacao": installation_number,
                "meses": months,
            },
        )
        if result is None:
            return []

        bills: list[CPFLBill] = []
        raw_list = result if isinstance(result, list) else result.get("data", [])
        if isinstance(raw_list, list):
            for item in raw_list:
                if not isinstance(item, dict):
                    continue
                bills.append(
                    CPFLBill(
                        reference_month=item.get("mesReferencia", item.get(KEY_REFERENCIA, "")),
                        due_date=item.get("dataVencimento", item.get(KEY_VENCIMENTO, "")),
                        amount=float(item.get(KEY_VALOR, 0) or 0),
                        consumption_kwh=float(
                            item.get(KEY_CONSUMO, item.get(KEY_KWH, 0)) or 0
                        ),
                        status=item.get("situacao", item.get("status", "")),
                    )
                )
        return bills

    def get_current_bill(self, installation_number: str) -> CPFLBill | None:
        """Get the most recent (current) open bill."""
        bills = self.get_invoice_history(installation_number, months=3)
        if not bills:
            return None
        # Return the first open or most recent bill
        for bill in bills:
            if bill.status.lower() in ("aberta", "open", "vencida", "overdue"):
                return bill
        return bills[0]

    def get_paid_invoices(
        self,
        installation_number: str,
        months: int = 12,
    ) -> list[CPFLBill]:
        """Get paid (quitadas) invoices for the installation."""
        result = self._request(
            "GET",
            PATH_PAID_INVOICES,
            params={
                "instalacao": installation_number,
                "meses": months,
            },
        )
        if result is None:
            return []

        bills: list[CPFLBill] = []
        raw_list = result if isinstance(result, list) else result.get("data", [])
        if isinstance(raw_list, list):
            for item in raw_list:
                if not isinstance(item, dict):
                    continue
                bills.append(
                    CPFLBill(
                        reference_month=item.get("mesReferencia", item.get(KEY_REFERENCIA, "")),
                        due_date=item.get("dataVencimento", item.get(KEY_VENCIMENTO, "")),
                        amount=float(item.get(KEY_VALOR, 0) or 0),
                        consumption_kwh=float(
                            item.get(KEY_CONSUMO, item.get(KEY_KWH, 0)) or 0
                        ),
                        status="paga",
                    )
                )
        return bills

    # -- Utility -------------------------------------------------------------

    def get_balance(self, installation_number: str) -> float:
        """Get the current account balance (negative = credit, positive = debit)."""
        info = self.get_installation_info(installation_number)
        if isinstance(info, dict):
            # CPFL may return balance in various fields
            balance = info.get("saldo", info.get("debito", 0))
            try:
                return float(balance or 0)
            except (TypeError, ValueError):
                return 0.0
        return 0.0
