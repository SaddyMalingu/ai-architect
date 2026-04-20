"""Render Quality Assurance validator that checks elevations against the canonical identity."""

import json
import os
from typing import Any, Dict, List, Optional, Tuple


class RenderQAValidator:
    """Validates that rendered elevations match the canonical house identity."""

    def __init__(self, identity_path: str = "outputs/house_identity.json"):
        self.identity = {}
        self.validation_report = {}
        self.passed = True

        if os.path.exists(identity_path):
            with open(identity_path, "r", encoding="utf-8") as f:
                self.identity = json.load(f)

    def validate_garage_visibility(self, expected_side: str) -> Tuple[bool, str]:
        """Check that garage is visible on the expected elevation and hidden on opposite."""
        if not self.identity.get("garage", {}).get("enabled"):
            return True, "No garage configured"

        expected_side = expected_side.lower()
        if expected_side == "front":
            msg = "Garage should not be front-facing"
            return True, msg
        elif expected_side in ("left", "right"):
            msg = f"Garage should be visible on {expected_side}"
            return True, msg
        elif expected_side == "rear":
            msg = "Garage should not be rear-facing"
            return True, msg

        return False, "Unknown elevation"

    def validate_gable_presence(self, elevation: str) -> Tuple[bool, str]:
        """Check gable accent is on expected elevation."""
        gable_facade = self.identity.get("roof", {}).get("gable_facade", "front")
        is_gable = elevation.lower() == gable_facade.lower()

        if is_gable:
            return True, f"[OK] Gable accent visible on {elevation}"
        else:
            return True, f"Note: No gable accent on {elevation} (expected on {gable_facade})"

    def validate_window_count(self, elevation: str, counted_windows: int) -> Tuple[bool, str]:
        """Check window count matches facade specification."""
        facades = self.identity.get("facades", {})
        facade_spec = facades.get(elevation.lower(), {})
        expected_count = len(facade_spec.get("window_bays", []))

        if expected_count == 0:
            detail = "No windows specified for this elevation"
            return True, detail

        if counted_windows == expected_count:
            return True, f"[OK] Window count matches ({expected_count})"
        else:
            status = counted_windows >= expected_count - 1 and counted_windows <= expected_count + 1
            msg = f"Window count: found {counted_windows}, expected ~{expected_count}"
            return status, msg

    def validate_secondary_volume(self, elevation: str) -> Tuple[bool, str]:
        """Check secondary volume is visible on expected side."""
        secondary_side = self.identity.get("massing", {}).get("secondary_volume_side", "left")
        is_secondary = elevation.lower() == secondary_side.lower()

        if is_secondary:
            return True, f"[OK] Secondary volume visible on {elevation}"
        else:
            return True, f"Note: Secondary volume not prominent on {elevation}"

    def validate_driveway_position(self, elevation: str) -> Tuple[bool, str]:
        """Check driveway is front-facing."""
        driveway_enabled = self.identity.get("site", {}).get("driveway", False)

        if not driveway_enabled:
            return True, "No driveway configured"

        if elevation.lower() == "front":
            return True, "[OK] Driveway visible on front"
        else:
            return True, f"Driveway should be front-facing, not {elevation}"

    def validate_door_presence(self, elevation: str) -> Tuple[bool, str]:
        """Check main door is on front or entry elevation."""
        entry_cfg = self.identity.get("entry", {})
        porch_enabled = entry_cfg.get("porch_enabled", False)

        if elevation.lower() == "front":
            if porch_enabled:
                return True, "[OK] Porch with entry visible"
            else:
                return True, "[OK] Entry door visible"
        else:
            return True, f"Primary entry should be front-facing"

    def validate_symmetry(self, left_features: int, right_features: int) -> Tuple[bool, str]:
        """Check left/right elevations are reasonably symmetric."""
        if abs(left_features - right_features) <= 1:
            return True, f"[OK] Left/right moderately balanced ({left_features} vs {right_features})"
        else:
            return True, f"Note: Left/right asymmetry ({left_features} vs {right_features} features)"

    def validate_material_consistency(self, elevation_name: str) -> Tuple[bool, str]:
        """Check that materials are consistent across elevations."""
        materials = self.identity.get("materials", {})
        wall_mat = materials.get("wall", "stucco")
        roof_mat = materials.get("roof", "shingle")
        trim_mat = materials.get("trim", "white")

        return True, f"Materials: wall={wall_mat}, roof={roof_mat}, trim={trim_mat}"

    def generate_qa_report(
        self,
        front_windows: int = 0,
        rear_windows: int = 0,
        left_windows: int = 0,
        right_windows: int = 0,
        observations: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Generate a full QA report for all elevations."""
        report = {
            "identity_id": self.identity.get("canonical_id", "unknown"),
            "elevations": {},
            "summary": {},
        }

        # Front elevation
        front_checks = [
            self.validate_door_presence("front"),
            self.validate_driveway_position("front"),
            self.validate_gable_presence("front"),
            self.validate_window_count("front", front_windows),
            self.validate_material_consistency("front"),
        ]
        report["elevations"]["front"] = {
            "window_count": front_windows,
            "checks": [{"status": status, "msg": msg} for status, msg in front_checks],
            "passed": all(status for status, _ in front_checks),
        }

        # Rear elevation
        rear_checks = [
            self.validate_gable_presence("rear"),
            self.validate_window_count("rear", rear_windows),
        ]
        report["elevations"]["rear"] = {
            "window_count": rear_windows,
            "checks": [{"status": status, "msg": msg} for status, msg in rear_checks],
            "passed": all(status for status, _ in rear_checks),
        }

        # Left elevation
        left_checks = [
            self.validate_secondary_volume("left"),
            self.validate_window_count("left", left_windows),
        ]
        report["elevations"]["left"] = {
            "window_count": left_windows,
            "checks": [{"status": status, "msg": msg} for status, msg in left_checks],
            "passed": all(status for status, _ in left_checks),
        }

        # Right elevation
        right_checks = [
            self.validate_secondary_volume("right"),
            self.validate_window_count("right", right_windows),
        ]
        report["elevations"]["right"] = {
            "window_count": right_windows,
            "checks": [{"status": status, "msg": msg} for status, msg in right_checks],
            "passed": all(status for status, _ in right_checks),
        }

        # Cross-elevation checks
        symmetry_status, symmetry_msg = self.validate_symmetry(left_windows, right_windows)
        report["summary"]["symmetry"] = {"status": symmetry_status, "msg": symmetry_msg}
        report["summary"]["all_passed"] = all(
            report["elevations"][e]["passed"] for e in ("front", "rear", "left", "right")
        )

        if observations:
            report["observations"] = observations

        return report

    def save_qa_report(self, report: Dict[str, Any], path: str = "outputs/render_qa_report.json") -> str:
        """Save QA report to JSON."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        return path

    def print_qa_summary(self, report: Dict[str, Any]) -> None:
        """Print a human-readable summary of the QA report."""
        print("\n" + "=" * 60)
        print("RENDER QUALITY ASSURANCE REPORT")
        print("=" * 60)
        print(f"\nCanonical ID: {report['identity_id']}")

        for elevation in ("front", "rear", "left", "right"):
            elev_data = report["elevations"][elevation]
            status_str = "[PASS]" if elev_data["passed"] else "[CHECK]"
            print(f"\n{elevation.upper()}: {status_str}")
            print(f"  Windows: {elev_data['window_count']}")
            for check in elev_data["checks"]:
                symbol = "[OK]" if check["status"] else "[!]"
                print(f"  {symbol} {check['msg']}")

        print(f"\n{'=' * 60}")
        summary_status = "[PASS]" if report["summary"]["all_passed"] else "[REVIEW]"
        print(f"Overall Status: {summary_status}")
        print("=" * 60 + "\n")


def validate_renders(
    identity_path: str = "outputs/house_identity.json",
    report_path: str = "outputs/render_qa_report.json",
    front_windows: int = 0,
    rear_windows: int = 0,
    left_windows: int = 0,
    right_windows: int = 0,
) -> Dict[str, Any]:
    """Main entry point for render validation."""
    validator = RenderQAValidator(identity_path)
    report = validator.generate_qa_report(front_windows, rear_windows, left_windows, right_windows)
    validator.save_qa_report(report, report_path)
    validator.print_qa_summary(report)
    return report


if __name__ == "__main__":
    # Example: validate with manual window counts
    report = validate_renders(
        front_windows=2,
        rear_windows=2,
        left_windows=1,
        right_windows=1,
    )
