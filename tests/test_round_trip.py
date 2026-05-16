from pathlib import Path

from eec.demo_data import generate_customers
from eec.container_builder import build_all_containers
from eec.container_reader import validate_container, extract_container
from eec.indexer import rebuild_index
from eec.search import search_index
from eec.corruption import corrupt_container_payload


def test_round_trip(tmp_path: Path):
    source = tmp_path / "source"
    containers = tmp_path / "containers"
    extracted = tmp_path / "extracted"
    index = tmp_path / "index" / "evidence.db"

    generate_customers(source, customers=2, target_mb_per_customer=1, seed=7)
    outs = build_all_containers(source, containers)
    assert len(outs) == 2

    validation = validate_container(outs[0])
    assert validation.status == "PASS"
    assert validation.checked_payloads > 5

    extracted_files = extract_container(outs[0], extracted)
    assert extracted_files

    indexed = rebuild_index(containers, index)
    assert indexed > 10
    rows = search_index(index, "source wealth", limit=10)
    assert rows

    corrupt = containers / "corrupt.fits"
    corrupt_container_payload(outs[0], corrupt, object_index=2)
    corrupt_validation = validate_container(corrupt)
    assert corrupt_validation.status == "FAIL"
    assert corrupt_validation.failed_payloads == 1
