from datetime import datetime, timezone

import pytest

from traffic_tracking.ajaxpro import AjaxProParseError, parse, parse_ajax_date


def test_parses_nested_ajax_datatables() -> None:
    source = (
        '{"value":new Ajax.Web.DataTable('
        '[["CamId"],["Location"]],'
        '[["cam-1",new Ajax.Web.DataTable([["Shape"]],[["POINT(106.7 10.8)"]])]])}'
    )

    parsed = parse(source)

    row = parsed["value"]["Rows"][0]
    assert row["CamId"] == "cam-1"
    assert row["Location"]["Rows"][0]["Shape"] == "POINT(106.7 10.8)"


def test_rejects_javascript_outside_supported_constructor() -> None:
    with pytest.raises(AjaxProParseError):
        parse('{"value":alert("unsafe")}')


def test_parses_ajax_timestamp_as_utc() -> None:
    assert parse_ajax_date("/Date(0+0700)/") == datetime(1970, 1, 1, tzinfo=timezone.utc)
    assert parse_ajax_date("not-a-date") is None
