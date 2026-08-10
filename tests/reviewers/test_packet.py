from skillcheck.reviewers.packet import build_packets


def test_packet_excludes_exact_duplicates_and_redacts_secrets() -> None:
    groups = [
        {"group_id": "exact", "relation": "EXACT_DUPLICATE", "body": "hidden"},
        {"group_id": "overlap", "relation": "HIGH_OVERLAP", "evidence": ["token=sk-secret-value"]},
    ]
    packets = build_packets(groups, max_groups=10, max_chars=20_000, allow_full_text=False)
    serialized = packets[0].model_dump_json()
    assert "EXACT_DUPLICATE" not in serialized
    assert "sk-secret-value" not in serialized
    assert "[REDACTED]" in serialized


def test_packets_are_bounded_and_stable() -> None:
    groups = [{"group_id": f"g{i}", "relation": "HIGH_OVERLAP", "evidence": ["x" * 40]} for i in range(5)]
    packets = build_packets(groups, max_groups=2, max_chars=500)
    assert [packet.packet_id for packet in packets] == ["review-packet-001", "review-packet-002", "review-packet-003"]
    assert all(len(packet.groups) <= 2 for packet in packets)
