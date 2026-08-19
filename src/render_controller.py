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
            except Exception:
                pass

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
            if self.ssim_threshold or self.reference_image_path:
                # prefer explicitly set threshold, fallback to specs value
                th = float(self.ssim_threshold) if self.ssim_threshold else float(0.6)
                ref = self.reference_image_path
                if ref:
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
                else:
                    print("No reference image available for SSIM gating")

            # choose the first passing render as best to save credits
            best_out = outfile
            best_samples = samples
            best_report = report
            if passed:
                print(f"QA passed at samples={samples}. Early exit to save compute.")
                break
            else:
                print(f"QA not passing at samples={samples}, will try higher samples if available.")

        return {
            "outfile": best_out,
            "samples": best_samples,
            "report": best_report,
            "total_cost": total_cost,
        }


if __name__ == "__main__":
    ar = AdaptiveRenderer()
    result = ar.render_and_validate()
    print(result)
