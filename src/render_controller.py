import json
import os
import time
from typing import Dict, List, Optional

from step4_blender import render_glb_with_blender
from render_qa import RenderQAValidator


class AdaptiveRenderer:
    """Adaptive renderer that runs progressive renders at increasing quality
    and stops early when QA passes to save compute credit.
    """

    def __init__(
        self,
        infile: str = "outputs/3d_models/house.glb",
        out_base: str = "outputs/renders/house_render",
        specs_path: str = "outputs/specs.json",
        identity_path: str = "outputs/house_identity.json",
        sample_schedule: Optional[List[int]] = None,
        resolution=(1280, 720),
        max_budget: float = 1e9,
    ):
        self.infile = infile
        self.out_base = out_base
        self.specs_path = specs_path
        self.identity_path = identity_path
        self.sample_schedule = sample_schedule or [16, 48, 96]
        self.resolution = resolution
        self.max_budget = max_budget
        self.reference_image_path = None
        self.ssim_threshold = None

        # allow passing via specs or later assignment
        if isinstance(self.specs_path, str) and os.path.exists(self.specs_path):
            try:
                with open(self.specs_path, "r", encoding="utf-8") as f:
                    specs = json.load(f)
                self.reference_image_path = specs.get("reference_image") or specs.get("reference_image_path")
                self.ssim_threshold = specs.get("ssim_threshold")
                self.enable_ssim_gating = bool(specs.get("enable_ssim_gating", False))
            except Exception:
                pass
        else:
            self.enable_ssim_gating = False
        # upgrade policy
        self.max_upgrades = 2
        self.upgrade_sample_factor = 2
        self.max_samples = 512
        self.max_resolution = (3840, 2160)

    def _read_identity_counts(self):
        try:
            with open(self.identity_path, "r", encoding="utf-8") as f:
                identity = json.load(f)
        except Exception:
            return 0, 0, 0, 0

        def count_windows(side: str):
            return len(identity.get("facades", {}).get(side, {}).get("window_bays", []))

        return (
            count_windows("front"),
            count_windows("rear"),
            count_windows("left"),
            count_windows("right"),
        )

    def _estimate_cost(self, samples: int) -> float:
        # very rough cost model: samples * pixels
        px = int(self.resolution[0]) * int(self.resolution[1])
        return samples * px / (1024.0 * 1024.0)  # unit: sample-megapixels

    def render_and_validate(self) -> Dict[str, object]:
        front, rear, left, right = self._read_identity_counts()
        total_cost = 0.0
        best_out = None
        best_samples = None
        best_report = None

        for samples in self.sample_schedule:
            outfile = f"{self.out_base}_{samples}.png"
            if os.path.exists(outfile):
                print(f"Using cached render for samples={samples}: {outfile}")
            else:
                est = self._estimate_cost(samples)
                if total_cost + est > self.max_budget:
                    print("Budget exhausted, stopping further renders")
                    break
                denoise = samples >= 64
                t0 = time.time()
                try:
                    render_glb_with_blender(
                        infile=self.infile,
                        outfile=outfile,
                        specs_path=self.specs_path,
                        identity_path=self.identity_path,
                        samples=samples,
                        denoise=denoise,
                        resolution=self.resolution,
                    )
                except Exception as e:
                    print(f"Render failed at samples={samples}: {e}")
                    continue
                dt = time.time() - t0
                total_cost += est
                print(f"Render completed samples={samples} time={dt:.1f}s est_cost={est:.3f}")

            # run QA on the produced render (quick heuristic)
            validator = RenderQAValidator(self.identity_path)
            report = validator.generate_qa_report(front, rear, left, right)
            passed = report.get("summary", {}).get("all_passed", False)

            # optionally run SSIM gating if a reference and threshold are available
            if getattr(self, "enable_ssim_gating", False) and self.reference_image_path:
                # SSIM gating only active when explicitly enabled in specs (enable_ssim_gating=true)
                th = float(self.ssim_threshold) if self.ssim_threshold else float(0.6)
                ref = self.reference_image_path
                try:
                    s_pass, s_msg, s_score = validator.validate_ssim(ref, outfile, threshold=th)
                    report.setdefault("summary", {})["ssim_check"] = {"passed": s_pass, "msg": s_msg, "score": s_score}
                    if not s_pass:
                        passed = False
                        print(f"SSIM gating: {s_msg}")
                    else:
                        print(f"SSIM gating: {s_msg}")
                except Exception as e:
                    print(f"SSIM gating failed: {e}")

            # choose the first passing render as best to save credits
            best_out = outfile
            best_samples = samples
            best_report = report
            if passed:
                print(f"QA passed at samples={samples}. Early exit to save compute.")
                break
            else:
                print(f"QA not passing at samples={samples}, will try higher samples if available.")
                # run upgrade policy: try a few higher-quality retries before moving on
                upgraded = self._attempt_upgrades(outfile, samples, validator)
                if upgraded:
                    # upgraded contains (outfile,samples,report)
                    best_out, best_samples, best_report = upgraded
                    print(f"Upgrade succeeded, using upgraded render: {best_out} (samples={best_samples})")
                    break
                else:
                    print("Upgrades did not resolve QA issues; continuing schedule.")

        return {
            "outfile": best_out,
            "samples": best_samples,
            "report": best_report,
            "total_cost": total_cost,
        }

    def _attempt_upgrades(self, current_outfile: str, current_samples: int, validator: RenderQAValidator):
        """Try progressive upgrades (higher samples / resolution) then a composite fallback.

        Returns (outfile, samples, report) on success, or None on failure.
        """
        samples = int(current_samples)
        for upgrade in range(self.max_upgrades):
            samples = min(samples * self.upgrade_sample_factor, self.max_samples)
            upgraded_out = f"{self.out_base}_{samples}_up.png"
            denoise = True
            res_x = min(int(self.resolution[0] * (1.5 ** (upgrade + 1))), self.max_resolution[0])
            res_y = min(int(self.resolution[1] * (1.5 ** (upgrade + 1))), self.max_resolution[1])
            try:
                print(f"Attempting upgrade render: samples={samples}, res=({res_x},{res_y}) -> {upgraded_out}")
                render_glb_with_blender(
                    infile=self.infile,
                    outfile=upgraded_out,
                    specs_path=self.specs_path,
                    identity_path=self.identity_path,
                    samples=samples,
                    denoise=denoise,
                    resolution=(res_x, res_y),
                )
            except Exception as e:
                print(f"Upgrade render failed: {e}")
                continue

            # run QA + SSIM if available
            front, rear, left, right = self._read_identity_counts()
            report = validator.generate_qa_report(front, rear, left, right)
            passed = report.get("summary", {}).get("all_passed", False)
            if self.ssim_threshold and self.reference_image_path:
                try:
                    s_pass, s_msg, s_score = validator.validate_ssim(self.reference_image_path, upgraded_out, threshold=self.ssim_threshold)
                    report.setdefault("summary", {})["ssim_check"] = {"passed": s_pass, "msg": s_msg, "score": s_score}
                    if not s_pass:
                        passed = False
                except Exception as e:
                    print(f"SSIM check on upgrade failed: {e}")

            if passed:
                return (upgraded_out, samples, report)

        # last resort: try a composite/high-quality fallback
        try:
            fallback_out = self._composite_fallback(current_outfile)
            if fallback_out:
                front, rear, left, right = self._read_identity_counts()
                report = validator.generate_qa_report(front, rear, left, right)
                if self.ssim_threshold and self.reference_image_path:
                    try:
                        s_pass, s_msg, s_score = validator.validate_ssim(self.reference_image_path, fallback_out, threshold=self.ssim_threshold)
                        report.setdefault("summary", {})["ssim_check"] = {"passed": s_pass, "msg": s_msg, "score": s_score}
                        if s_pass:
                            return (fallback_out, samples, report)
                    except Exception as e:
                        print(f"SSIM check on fallback failed: {e}")

        except Exception as e:
            print(f"Composite fallback failed: {e}")

        return None

    def _composite_fallback(self, base_outfile: str) -> Optional[str]:
        """A conservative high-quality re-render used as a fallback. Returns new outfile path or None."""
        fallback_samples = min(self.max_samples, max(256, int(self.sample_schedule[-1] * 2)))
        fallback_res = self.max_resolution
        fallback_out = f"{self.out_base}_fallback.png"
        print(f"Running composite fallback render samples={fallback_samples} res={fallback_res}")
        try:
            render_glb_with_blender(
                infile=self.infile,
                outfile=fallback_out,
                specs_path=self.specs_path,
                identity_path=self.identity_path,
                samples=fallback_samples,
                denoise=True,
                resolution=fallback_res,
            )
            return fallback_out
        except Exception as e:
            print(f"Fallback render failed: {e}")
            return None


if __name__ == "__main__":
    ar = AdaptiveRenderer()
    result = ar.render_and_validate()
    print(result)
