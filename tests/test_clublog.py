import json

import pytest

from app.clublog import ClubLogError, fetch_rankings, parse_rankings


def good_payload(reference):
    ids = [e.dxcc for e in reference.current]
    return json.dumps({str(i + 1): str(d) for i, d in enumerate(ids)}).encode()


def test_good_response(reference):
    ranks = parse_rankings(good_payload(reference), reference)
    assert len(ranks) == 340
    assert ranks[reference.current[0].dxcc] == 1


def test_fetch_uses_injected_fetcher(reference):
    assert len(fetch_rankings(reference, fetch=lambda: good_payload(reference))) == 340


@pytest.mark.parametrize("payload, msg", [
    (b"<html>error</html>", "not valid JSON"),
    (b"[1, 2, 3]", "expected ranking"),
    (json.dumps({"1": "1"}).encode(), "entries"),
])
def test_bad_shapes(reference, payload, msg):
    with pytest.raises(ClubLogError, match=msg):
        parse_rankings(payload, reference)


def test_unknown_dxcc(reference):
    obj = json.loads(good_payload(reference))
    obj["1"] = "999"
    with pytest.raises(ClubLogError, match="not a current entity"):
        parse_rankings(json.dumps(obj).encode(), reference)


def test_deleted_dxcc_rejected(reference):
    obj = json.loads(good_payload(reference))
    obj["1"] = "196"                                    # deleted Palestine
    with pytest.raises(ClubLogError, match="not a current entity"):
        parse_rankings(json.dumps(obj).encode(), reference)


def test_duplicate_dxcc(reference):
    obj = json.loads(good_payload(reference))
    obj["2"] = obj["1"]
    with pytest.raises(ClubLogError, match="twice"):
        parse_rankings(json.dumps(obj).encode(), reference)


def test_non_numeric(reference):
    obj = json.loads(good_payload(reference))
    obj["1"] = "abc"
    with pytest.raises(ClubLogError, match="non-numeric"):
        parse_rankings(json.dumps(obj).encode(), reference)


def test_network_failure_surfaces_as_clublog_error(reference):
    def boom():
        raise ClubLogError("Could not reach Club Log: timed out")
    with pytest.raises(ClubLogError, match="Could not reach"):
        fetch_rankings(reference, fetch=boom)


def test_rank_gaps_and_duplicates_rejected(reference):
    obj = json.loads(good_payload(reference))
    obj["01"] = obj.pop("1")                            # "01" is still rank 1 (allowed)
    obj["400"] = obj.pop("2")                           # gap at 2
    with pytest.raises(ClubLogError, match="sequence"):
        parse_rankings(json.dumps(obj).encode(), reference)


def test_float_values_rejected(reference):
    obj = json.loads(good_payload(reference))
    obj["1"] = 344.9
    with pytest.raises(ClubLogError, match="non-numeric"):
        parse_rankings(json.dumps(obj).encode(), reference)
