"""SAWA — Salary Value Benchmark.

Flask backend that translates country names picked in the UI into ISO
alpha-3 codes and delegates the actual PPP math to ppp_converter.py.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from flask import Flask, jsonify, render_template, request

from countries import COUNTRIES, code_for_name
from ppp_converter import (
    PPPConverter,
    PPPError,
    WorldBankPPPClient,
)

app = Flask(__name__)

# Single shared converter instance: WorldBankPPPClient is stateless aside
# from its timeout, so there is no need to rebuild it per request.
converter = PPPConverter(client=WorldBankPPPClient())


@app.get("/")
def index():
    # Sorted names give a predictable, alphabetized dropdown regardless of
    # the underlying dict's insertion order.
    country_names = sorted(COUNTRIES.keys())
    return render_template("index.html", country_names=country_names)


@app.post("/api/convert")
def api_convert():
    payload = request.get_json(silent=True) or {}

    source_name = payload.get("source_country", "").strip()
    target_name = payload.get("target_country", "").strip()
    raw_salary = str(payload.get("salary", "")).strip().replace(",", "")

    # Validate presence up front so we return one clear error instead of
    # letting a KeyError/InvalidOperation bubble up from deeper calls.
    if not source_name or not target_name:
        return jsonify(error="Please choose both a source and target country."), 400

    if source_name == target_name:
        return jsonify(error="Source and target countries must be different."), 400

    try:
        salary = Decimal(raw_salary)
    except InvalidOperation:
        return jsonify(error="Enter a valid numeric salary."), 400

    if salary <= 0:
        return jsonify(error="Salary must be greater than zero."), 400

    try:
        source_code = code_for_name(source_name)
        target_code = code_for_name(target_name)
    except KeyError as exc:
        return jsonify(error=f"Unrecognized country: {exc.args[0]}"), 400

    try:
        result = converter.convert(
            salary=salary,
            source_country=source_code,
            target_country=target_code,
        )
    except PPPError as exc:
        return jsonify(error=str(exc)), 502

    return jsonify(
        equivalent_salary=f"{result.equivalent_salary:,.2f}",
        source_salary=f"{result.source_salary:,.2f}",
        source_country=source_name,
        target_country=target_name,
        data_year=result.data_year,
    )


if __name__ == "__main__":
    import os

    # Render (and most PaaS hosts) inject PORT and expect the app to bind
    # 0.0.0.0; falling back to 5000/localhost keeps local dev unchanged.
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
