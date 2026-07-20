#!/usr/bin/env python3
"""Reject boot-order regressions in the Gemma systemd units."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent


def parse_unit(path: Path) -> dict[str, dict[str, list[str]]]:
    sections: dict[str, dict[str, list[str]]] = {}
    section: str | None = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            sections.setdefault(section, {})
            continue
        if section is None or "=" not in line:
            raise ValueError(f"{path}: invalid line: {raw_line!r}")
        key, value = line.split("=", 1)
        sections[section].setdefault(key.strip(), []).extend(value.split())

    return sections


def values(unit: dict[str, dict[str, list[str]]], section: str, key: str) -> set[str]:
    return set(unit.get(section, {}).get(key, []))


def main() -> None:
    stability = parse_unit(ROOT / "llm-stability-setup.service")
    primary = parse_unit(ROOT / "llm-gemma4-primary.service")
    rpc = parse_unit(ROOT / "llm-gpu2-rpc-worker.service")

    stability_after = values(stability, "Unit", "After")
    stability_wanted_by = values(stability, "Install", "WantedBy")

    assert "network-online.target" in stability_after
    assert "multi-user.target" in stability_wanted_by
    assert "multi-user.target" not in stability_after, (
        "llm-stability-setup.service is wanted by multi-user.target; ordering it "
        "after that target creates a boot cycle"
    )

    for name, unit in (("primary", primary), ("RPC worker", rpc)):
        assert "llm-stability-setup.service" in values(unit, "Unit", "After"), (
            f"{name} must start after llm-stability-setup.service"
        )

    print("Gemma systemd dependency checks: OK")


if __name__ == "__main__":
    main()
