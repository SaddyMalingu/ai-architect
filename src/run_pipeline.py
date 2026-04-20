# src/run_pipeline.py
import subprocess
import sys
from dotenv import load_dotenv
from step1_input import get_house_specs
from house_identity import build_house_identity, save_house_identity
from assets_manager import ensure_assets
from step2_floorplan_graph import generate_floorplan_graph, save_graph
from step3_geometry import layout_and_export
from step5_plan_generation import generate_floorplan_svg
from step6_manifest import create_manifest
from render_qa import RenderQAValidator
from datetime import datetime
import threading
import os
import json

# --- Logging setup for pipeline ---
LOG_FILE = "logs/backend.log"
os.makedirs("logs", exist_ok=True)
_log_lock = threading.Lock()

def log(msg: str):
    ts_kenya = datetime.utcnow().timestamp() + 3*3600  # UTC+3
    ts_kenya_str = datetime.utcfromtimestamp(ts_kenya).strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts_kenya_str} [Pipeline] {msg}"
    print(line, flush=True)
    with _log_lock:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")

def run(prompt=None):

    load_dotenv()
    if prompt is None:
        prompt = "3-bedroom modern house, 2 floors, open-plan living/kitchen, 2 bathrooms"
    log(f"Prompt: {prompt}")

    # Clear cached outputs for a fresh run
    import glob
    import shutil
    output_patterns = [
        "outputs/specs.json",
        "outputs/house_identity.json",
        "outputs/floorplan_graph.json",
        "outputs/3d_models/*",
        "outputs/plans/*",
        "outputs/renders/*",
        "outputs/manifest.json"
    ]
    for pattern in output_patterns:
        for f in glob.glob(pattern):
            try:
                if os.path.isfile(f):
                    os.remove(f)
                elif os.path.isdir(f):
                    shutil.rmtree(f)
            except Exception as e:
                log(f"Could not remove cached file {f}: {e}")

    specs = get_house_specs(prompt)
    log(f"Specs: {specs}")

    # download open-source textures/HDRI (Poly Haven)
    try:
        assets_manifest = ensure_assets()
        if assets_manifest:
            hdri_path = assets_manifest.get("hdri_path")
            texture_sets = assets_manifest.get("texture_sets")
            if hdri_path:
                specs["hdri_path"] = hdri_path
            if texture_sets:
                specs["texture_sets"] = texture_sets
            log("Assets ready: HDRI and texture sets.")
    except Exception as e:
        log(f"Asset download skipped (could not run). Error: {e}")

    os.makedirs("outputs", exist_ok=True)
    with open("outputs/specs.json", "w", encoding="utf-8") as f:
        json.dump(specs, f, indent=2)

    house_identity = build_house_identity(specs, prompt)
    save_house_identity(house_identity)
    log(f"Canonical house identity created: {house_identity.get('canonical_id')}")

    G = generate_floorplan_graph(specs)
    save_graph(G)
    log("Floorplan graph generated and saved.")

    layout_and_export()
    log("Layout and export completed.")

    generate_floorplan_svg()
    log("SVG floorplan generated.")

    create_manifest()
    log("Manifest created.")

    # call blender render if Blender is present
    try:
        from step4_blender import render_glb_with_blender
        render_glb_with_blender()
        log("Blender render executed.")
    except Exception as e:
        log(f"Blender render skipped (could not run). Install Blender and ensure it's in PATH. Error: {e}")

    # --- Post-render QA validation ---
    try:
        validator = RenderQAValidator("outputs/house_identity.json")
        front_win_count = len(house_identity.get("facades", {}).get("front", {}).get("window_bays", []))
        rear_win_count = len(house_identity.get("facades", {}).get("rear", {}).get("window_bays", []))
        left_win_count = len(house_identity.get("facades", {}).get("left", {}).get("window_bays", []))
        right_win_count = len(house_identity.get("facades", {}).get("right", {}).get("window_bays", []))
        qa_report = validator.generate_qa_report(
            front_windows=front_win_count,
            rear_windows=rear_win_count,
            left_windows=left_win_count,
            right_windows=right_win_count,
        )
        validator.save_qa_report(qa_report)
        validator.print_qa_summary(qa_report)
        log("Render QA validation complete.")
    except Exception as e:
        log(f"Render QA validation skipped: {e}")

    # --- Geometry Diagram Description analysis (post-process) ---
    try:
        import subprocess
        svg_path = "outputs/plans/floorplan.svg"
        analysis_out = "outputs/analysis/diagram_analysis.txt"
        os.makedirs("outputs/analysis", exist_ok=True)
        # Call the prototype/main.py script on the SVG
        result = subprocess.run([
            "python",
            "addons/geometry_diagram_description/Geometry-Diagram-Description-main/prototype/main.py",
            "--input", svg_path,
            "--output", analysis_out
        ], capture_output=True, text=True)
        log(f"Geometry Diagram Description analysis complete. Output: {analysis_out}\nStdout: {result.stdout}\nStderr: {result.stderr}")
    except Exception as e:
        log(f"Geometry Diagram Description analysis skipped or failed: {e}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", type=str, help="House prompt", default=None)
    args = parser.parse_args()
    run(args.prompt)
