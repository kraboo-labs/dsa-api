from core.enums import AreaEnum, EventType, ScrapeRunStatus, TFStatus


def test_area_enum_has_eighteen_values():
    assert len(AreaEnum) == 18


def test_area_enum_csam_value():
    assert AreaEnum.csam.value == "csam"


def test_tf_status_values():
    assert {s.value for s in TFStatus} == {"active", "suspended", "revoked"}


def test_event_type_values():
    assert {e.value for e in EventType} == {"created", "updated", "removed", "restored"}


def test_scrape_run_status_values():
    assert {s.value for s in ScrapeRunStatus} == {"running", "success", "failed", "partial"}
