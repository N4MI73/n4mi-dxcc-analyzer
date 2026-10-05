from collections import Counter

from app.reference import normalize_name


def test_counts(reference):
    assert len(reference) == 402
    assert len(reference.current) == 340


def test_every_current_entity_has_continent_and_zone(reference):
    for e in reference.current:
        assert e.continent in {"AF", "AN", "AS", "EU", "NA", "OC", "SA"}, e
        assert e.cq_zone and 1 <= e.cq_zone <= 40, e


def test_known_continents(reference):
    assert reference.by_dxcc[47].continent == "SA"     # Easter Island (Lovable had OC)
    assert reference.by_dxcc[54].continent == "EU"     # European Russia
    assert reference.by_dxcc[15].continent == "AS"     # Asiatic Russia


def test_same_name_current_and_deleted(reference):
    # PALESTINE is both a current (510, E4) and a deleted (196) entity.
    assert reference.lookup("PALESTINE", deleted=False).dxcc == 510
    assert reference.lookup("PALESTINE", deleted=True).dxcc == 196


def test_lookup_ignores_case_and_spacing(reference):
    assert reference.lookup("  cape   verde ", False).dxcc == 409
    assert reference.lookup("CAPE\xa0VERDE", False).dxcc == 409
    assert normalize_name(" a  b ") == "A B"


def test_shared_prefixes_are_distinct_entities(reference):
    shared = Counter(e.prefix for e in reference.current if e.prefix)
    assert shared["3Y"] == 2 and shared["VP8"] == 5 and shared["HK0"] == 2
    bouvet = reference.lookup("BOUVET ISLAND", False)
    peter = reference.lookup("PETER 1 ISLAND", False)
    assert bouvet.prefix == peter.prefix == "3Y"
    assert bouvet.dxcc != peter.dxcc


def test_blank_prefix(reference):
    assert reference.lookup("SPRATLY ISLANDS", False).prefix == ""
