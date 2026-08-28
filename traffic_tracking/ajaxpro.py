from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from typing import Any


class AjaxProParseError(ValueError):
    pass


@dataclass(slots=True)
class DataTable:
    columns: list[Any]
    rows: list[Any]

    def normalized(self) -> dict[str, Any]:
        names = [column[0] if isinstance(column, list) and column else str(column) for column in self.columns]
        normalized_rows: list[dict[str, Any]] = []
        for row in self.rows:
            if not isinstance(row, list):
                raise AjaxProParseError("DataTable row is not an array")
            normalized_rows.append({name: normalize(value) for name, value in zip(names, row)})
        return {"Columns": names, "Rows": normalized_rows}


class Parser:
    constructor = "new Ajax.Web.DataTable"

    def __init__(self, source: str):
        self.source = source
        self.position = 0
        self.decoder = json.JSONDecoder()

    def parse(self) -> Any:
        value = self._value()
        self._whitespace()
        if self.position != len(self.source):
            raise AjaxProParseError(f"Unexpected trailing data at offset {self.position}")
        return normalize(value)

    def _whitespace(self) -> None:
        while self.position < len(self.source) and self.source[self.position].isspace():
            self.position += 1

    def _value(self) -> Any:
        self._whitespace()
        if self.position >= len(self.source):
            raise AjaxProParseError("Unexpected end of response")
        if self.source.startswith(self.constructor, self.position):
            return self._data_table()
        char = self.source[self.position]
        if char == "{":
            return self._object()
        if char == "[":
            return self._array()
        if char == '"':
            return self._json_scalar()
        for literal, value in (("true", True), ("false", False), ("null", None)):
            if self.source.startswith(literal, self.position):
                self.position += len(literal)
                return value
        if char == "-" or char.isdigit():
            return self._json_scalar()
        raise AjaxProParseError(f"Unsupported token at offset {self.position}")

    def _json_scalar(self) -> Any:
        try:
            value, end = self.decoder.raw_decode(self.source, self.position)
        except json.JSONDecodeError as exc:
            raise AjaxProParseError(str(exc)) from exc
        self.position = end
        return value

    def _array(self) -> list[Any]:
        self.position += 1
        values: list[Any] = []
        self._whitespace()
        if self._consume("]"):
            return values
        while True:
            values.append(self._value())
            self._whitespace()
            if self._consume("]"):
                return values
            self._expect(",")

    def _object(self) -> dict[str, Any]:
        self.position += 1
        values: dict[str, Any] = {}
        self._whitespace()
        if self._consume("}"):
            return values
        while True:
            self._whitespace()
            key = self._json_scalar()
            if not isinstance(key, str):
                raise AjaxProParseError("Object key is not a string")
            self._whitespace()
            self._expect(":")
            values[key] = self._value()
            self._whitespace()
            if self._consume("}"):
                return values
            self._expect(",")

    def _data_table(self) -> DataTable:
        self.position += len(self.constructor)
        self._whitespace()
        self._expect("(")
        columns = self._value()
        self._whitespace()
        self._expect(",")
        rows = self._value()
        self._whitespace()
        self._expect(")")
        if not isinstance(columns, list) or not isinstance(rows, list):
            raise AjaxProParseError("DataTable arguments must be arrays")
        return DataTable(columns=columns, rows=rows)

    def _consume(self, token: str) -> bool:
        if self.source.startswith(token, self.position):
            self.position += len(token)
            return True
        return False

    def _expect(self, token: str) -> None:
        if not self._consume(token):
            raise AjaxProParseError(f"Expected {token!r} at offset {self.position}")


def normalize(value: Any) -> Any:
    if isinstance(value, DataTable):
        return value.normalized()
    if isinstance(value, list):
        return [normalize(item) for item in value]
    if isinstance(value, dict):
        return {key: normalize(item) for key, item in value.items()}
    return value


def parse(source: str) -> Any:
    return Parser(source).parse()


_DATE_RE = re.compile(r"^/Date\((-?\d+)(?:[+-]\d{4})?\)/$")


def parse_ajax_date(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    match = _DATE_RE.match(value)
    if not match:
        return None
    return datetime.fromtimestamp(int(match.group(1)) / 1000, tz=timezone.utc)
