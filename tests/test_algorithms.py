from dexfrag.algorithms import all_topologies, topology_for, structural_audit_report


def test_all_32_algorithms_present():
    topologies = all_topologies()
    assert len(topologies) == 32
    assert [t.number for t in topologies] == list(range(1, 33))


def test_topology_for_bounds():
    assert topology_for(1).number == 1
    assert topology_for(32).number == 32
    try:
        topology_for(0)
        assert False, "expected ValueError"
    except ValueError:
        pass
    try:
        topology_for(33)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_carrier_and_modulator_masks_partition_six_operators():
    for topology in all_topologies():
        assert topology.carrier_mask & topology.modulator_mask == 0
        assert topology.carrier_mask | topology.modulator_mask == 0b111111


def test_algorithm_32_has_no_modulation_edges_all_carriers():
    topology = topology_for(32)
    assert topology.edges == ()
    assert set(topology.carriers) == set(range(6))
    assert topology.modulator_mask == 0


def test_feedback_warm_mask_includes_feedback_source():
    for topology in all_topologies():
        source, _target = topology.feedback
        assert topology.feedback_warm_mask & (1 << source)


def test_structural_audit_report_is_reversible_and_complete():
    report = structural_audit_report()
    assert report["all_32_present"] is True
    assert report["algorithm_count"] == 32
    for entry in report["topologies"]:
        # Reversibility: edges/carriers/feedback in the derived report must
        # reproduce the exact raw values the topology was built from.
        rebuilt = topology_for(entry["number"])
        assert [list(e) for e in rebuilt.edges] == entry["edges"]
        assert list(rebuilt.carriers) == entry["carriers"]
        assert list(rebuilt.feedback) == entry["feedback"]


def test_no_two_algorithms_are_silently_merged_by_default():
    # Distinct algorithm numbers must remain distinct identities even when
    # some derived topology fields coincide (e.g. algorithms 1 and 2 differ
    # only by feedback location).
    numbers = [t.number for t in all_topologies()]
    assert len(numbers) == len(set(numbers)) == 32
