# src/step6_manifest.py
import json
import os

def create_manifest(manifest_path="outputs/manifest.json"):
    manifest = {
        "project_id": "proj_001",
        "graph": "outputs/floorplan_graph.json",
        "geometry": "outputs/3d_models/house.glb",
        "house_identity": "outputs/house_identity.json",
        "plans": ["outputs/plans/floorplan.svg"],
        "renders": [
            "outputs/renders/house_render_front.png",
            "outputs/renders/house_render_rear.png",
            "outputs/renders/house_render_left.png",
            "outputs/renders/house_render_right.png"
        ],
        "elevations": {
            "front": "outputs/renders/house_render_front.png",
            "rear": "outputs/renders/house_render_rear.png",
            "left": "outputs/renders/house_render_left.png",
            "right": "outputs/renders/house_render_right.png"
        },
        "elements": {}  # will populate basic mapping based on nodes
    }
    # try to populate elements from graph
    try:
        with open(manifest["graph"], "r") as f:
            g = json.load(f)
        for node in g.get("nodes", []):
            nid = node["id"]
            manifest["elements"][nid] = {
                "graph_node": nid,
                "geometry_node": nid,
                "svg_id": nid
            }
    except Exception:
        pass
    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Manifest written to {manifest_path}")

if __name__ == "__main__":
    create_manifest()
