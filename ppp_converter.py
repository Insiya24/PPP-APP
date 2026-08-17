from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import requests


WORLD_BANK_API = "https://api.worldbank.org/v2"

# Household/private-consumption PPP is more aligned with the purchasing
# decisions we are trying to approximate than economy-wide GDP PPP.
PPP_INDICATOR = "PA.NUS.PRVT.PP"

REQUEST_TIMEOUT_SECONDS = 10


class PPPError(Exception):
    """Base exception for PPP conversion failures."""


class WorldBankAPIError(PPPError):
    """Raised when World Bank data cannot be retrieved or interpreted."""


class PPPDataNotFoundError(PPPError):
    """Raised when PPP data is unavailable for a requested country."""


@dataclass(frozen=True)
class PPPObservation:
    country_code: str
    country_name: str
    year: int
    value: Decimal


@dataclass(frozen=True)
class PPPConversionResult:
    source_country: str
    target_country: str
    source_salary: Decimal
    equivalent_salary: Decimal
    source_ppp: Decimal
    target_ppp: Decimal
    data_year: int


class WorldBankPPPClient:
    def __init__(self, timeout: int = REQUEST_TIMEOUT_SECONDS) -> None:
        self.timeout = timeout

    def get_latest_ppp(
        self,
        country_code: str,
        indicator: str = PPP_INDICATOR,
    ) -> PPPObservation:
        country_code = self._normalize_country_code(country_code)

        url = (
            f"{WORLD_BANK_API}/country/"
            f"{country_code}/indicator/{indicator}"
        )

        params = {
            "format": "json",
            "per_page": 100,
        }

        try:
            response = requests.get(
                url,
                params=params,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise WorldBankAPIError(
                f"Failed to retrieve PPP data for {country_code}."
            ) from exc

        try:
            payload: Any = response.json()
        except ValueError as exc:
            raise WorldBankAPIError(
                "World Bank returned an invalid JSON response."
            ) from exc

        return self._extract_latest_observation(
            payload=payload,
            country_code=country_code,
        )

    @staticmethod
    def _normalize_country_code(country_code: str) -> str:
        if not isinstance(country_code, str):
            raise ValueError("Country code must be a string.")

        normalized = country_code.strip().upper()

        if len(normalized) not in {2, 3} or not normalized.isalpha():
            raise ValueError(
                "Country code must be a valid ISO-style 2 or 3 letter code."
            )

        return normalized

    @staticmethod
    def _extract_latest_observation(
        payload: Any,
        country_code: str,
    ) -> PPPObservation:
        if (
            not isinstance(payload, list)
            or len(payload) < 2
            or not isinstance(payload[1], list)
        ):
            raise WorldBankAPIError(
                f"Unexpected World Bank response for {country_code}."
            )

        observations = payload[1]

        for observation in observations:
            if not isinstance(observation, dict):
                continue

            value = observation.get("value")
            year = observation.get("date")
            country = observation.get("country")

            if value is None or year is None:
                continue

            if not isinstance(country, dict):
                country = {}

            try:
                ppp_value = Decimal(str(value))
                observation_year = int(year)
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise WorldBankAPIError(
                    f"Invalid PPP observation for {country_code}."
                ) from exc

            if ppp_value <= 0:
                continue

            return PPPObservation(
                country_code=country_code,
                country_name=country.get("value", country_code),
                year=observation_year,
                value=ppp_value,
            )

        raise PPPDataNotFoundError(
            f"No PPP data available for {country_code}."
        )


class PPPConverter:
    def __init__(self, client: WorldBankPPPClient) -> None:
        self.client = client

    def convert(
        self,
        salary: Decimal,
        source_country: str,
        target_country: str,
    ) -> PPPConversionResult:
        if salary <= 0:
            raise ValueError("Salary must be greater than zero.")

        source = self.client.get_latest_ppp(source_country)
        target = self.client.get_latest_ppp(target_country)

        # Comparing observations from different years would mix price levels
        # from different periods and make the result misleading.
        if source.year != target.year:
            source, target = self._align_years(
                source_country=source_country,
                target_country=target_country,
            )

        equivalent_salary = (
            salary / source.value
        ) * target.value

        return PPPConversionResult(
            source_country=source.country_name,
            target_country=target.country_name,
            source_salary=salary,
            equivalent_salary=equivalent_salary,
            source_ppp=source.value,
            target_ppp=target.value,
            data_year=source.year,
        )

    def _align_years(
        self,
        source_country: str,
        target_country: str,
    ) -> tuple[PPPObservation, PPPObservation]:
        source_history = self._get_history(source_country)
        target_history = self._get_history(target_country)

        source_by_year = {
            observation.year: observation
            for observation in source_history
        }
        target_by_year = {
            observation.year: observation
            for observation in target_history
        }

        common_years = set(source_by_year) & set(target_by_year)

        if not common_years:
            raise PPPDataNotFoundError(
                "No common PPP year exists between the two countries."
            )

        latest_common_year = max(common_years)

        return (
            source_by_year[latest_common_year],
            target_by_year[latest_common_year],
        )

    def _get_history(
        self,
        country_code: str,
    ) -> list[PPPObservation]:
        country_code = country_code.strip().upper()

        url = (
            f"{WORLD_BANK_API}/country/"
            f"{country_code}/indicator/{PPP_INDICATOR}"
        )

        try:
            response = requests.get(
                url,
                params={
                    "format": "json",
                    "per_page": 100,
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise WorldBankAPIError(
                f"Failed to retrieve PPP history for {country_code}."
            ) from exc

        if (
            not isinstance(payload, list)
            or len(payload) < 2
            or not isinstance(payload[1], list)
        ):
            raise WorldBankAPIError(
                f"Unexpected World Bank response for {country_code}."
            )

        observations: list[PPPObservation] = []

        for item in payload[1]:
            if not isinstance(item, dict):
                continue

            value = item.get("value")
            year = item.get("date")

            if value is None or year is None:
                continue

            try:
                ppp_value = Decimal(str(value))
                observation_year = int(year)
            except (InvalidOperation, TypeError, ValueError):
                continue

            if ppp_value <= 0:
                continue

            country = item.get("country") or {}

            observations.append(
                PPPObservation(
                    country_code=country_code,
                    country_name=country.get(
                        "value",
                        country_code,
                    ),
                    year=observation_year,
                    value=ppp_value,
                )
            )

        if not observations:
            raise PPPDataNotFoundError(
                f"No PPP history available for {country_code}."
            )

        return observations


def read_salary() -> Decimal:
    raw_salary = input("Enter annual salary: ").strip().replace(",", "")

    try:
        salary = Decimal(raw_salary)
    except InvalidOperation as exc:
        raise ValueError("Salary must be a valid number.") from exc

    if salary <= 0:
        raise ValueError("Salary must be greater than zero.")

    return salary


def main() -> None:
    print("\n=== PPP Salary Converter ===\n")

    try:
        salary = read_salary()

        source_country = input(
            "Source country code (e.g. IND): "
        ).strip()

        target_country = input(
            "Target country code (e.g. USA): "
        ).strip()

        converter = PPPConverter(
            client=WorldBankPPPClient()
        )

        result = converter.convert(
            salary=salary,
            source_country=source_country,
            target_country=target_country,
        )

        print("\n--- Result ---")
        print(
            f"Source: {result.source_country}"
        )
        print(
            f"Target: {result.target_country}"
        )
        print(
            f"Data year: {result.data_year}"
        )
        print(
            f"Source PPP factor: {result.source_ppp:,.4f}"
        )
        print(
            f"Target PPP factor: {result.target_ppp:,.4f}"
        )
        print(
            f"Input salary: {result.source_salary:,.2f}"
        )
        print(
            "PPP equivalent salary: "
            f"{result.equivalent_salary:,.2f}"
        )

    except (PPPError, ValueError) as exc:
        print(f"\nError: {exc}")


if __name__ == "__main__":
    main()