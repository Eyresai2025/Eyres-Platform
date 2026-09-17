####################yolo##############################################
from __future__ import annotations
import os, sys, json, glob, random, argparse
import numpy as np
import cv2
import argparse

# ---------- Utilities ----------
# --- safe_safe_print to avoid Windows CP1252 Unicode errors ---
def safe_print(*parts, **kw):
    msg = " ".join(str(p) for p in parts)
    try:
        print(msg, **kw)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "ignore").decode("ascii"), **kw)

def _color_for(id_int: int):
    random.seed(id_int * 101 + 7)
    return int(random.randint(72, 255)), int(random.randint(72, 255)), int(random.randint(72, 255))

def draw_vis(img_bgr, dets, alpha_mask=0.35, box_th=2, font_scale=0.6):
    """
    Robust visualizer:
    - Resizes masks to full image size before blending to avoid shape mismatches.
    - Clamps boxes to image bounds.
    """
    out = img_bgr.copy()
    overlay = out.copy()
    H, W = out.shape[:2]

    for i, d in enumerate(dets):
        x1, y1, x2, y2 = d["bbox"]
        name = d.get("name", str(d.get("cls", "?")))
        conf = float(d.get("conf", 0.0))
        color = _color_for(d.get("cls", i))

        # ---- SEGMENTATION MASK (robust: resize to img size) ----
        m = d.get("mask")
        if m is not None:
            if m.ndim == 3 and m.shape[-1] == 1:
                m = m[..., 0]
            m = (m > 0).astype(np.uint8)
            if m.shape[:2] != (H, W):
                m = cv2.resize(m, (W, H), interpolation=cv2.INTER_NEAREST)
            overlay[m == 1] = np.array(color, dtype=np.uint8)

        # ---- BOUNDING BOX (clamped) ----
        x1 = max(0, min(int(x1), W - 1)); x2 = max(0, min(int(x2), W - 1))
        y1 = max(0, min(int(y1), H - 1)); y2 = max(0, min(int(y2), H - 1))
        cv2.rectangle(out, (x1, y1), (x2, y2), color, box_th, lineType=cv2.LINE_AA)

        # ---- LABEL ----
        label = f"{name} {conf:.2f}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 2)
        y0 = max(0, y1 - th - 6)
        cv2.rectangle(out, (x1, y0), (x1 + tw + 4, y0 + th + 4), color, -1)
        cv2.putText(out, label, (x1 + 2, y0 + th), cv2.FONT_HERSHEY_SIMPLEX,
                    font_scale, (0, 0, 0), 2, cv2.LINE_AA)

        # ---- POSE KEYPOINTS ----
        kps = d.get("keypoints")
        if kps is not None:
            for (kx, ky) in kps:
                cv2.circle(out, (int(kx), int(ky)), 2, color, -1)

    # Blend colored overlay for masks
    out = cv2.addWeighted(overlay, alpha_mask, out, 1 - alpha_mask, 0)
    return out

def _ensure_dir(p):
    os.makedirs(p, exist_ok=True)
    return p

EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".mp4", ".avi", ".mov", ".mkv")

def list_media(input_path):
    if os.path.isdir(input_path):
        files = []
        for ext in EXTS:
            files.extend(glob.glob(os.path.join(input_path, f"*{ext}")))
        files.sort()
        return files
    if os.path.isfile(input_path):
        return [input_path]
    # glob
    allp = [p for p in glob.glob(input_path)]
    return [p for p in allp if os.path.splitext(p)[1].lower() in EXTS]

def _rows_from_dets(image_path, dets):
    rows, base = [], os.path.basename(image_path)
    for d in dets:
        x1, y1, x2, y2 = d["bbox"]
        rows.append({
            "image": base, "cls": d.get("cls"), "name": d.get("name"),
            "conf": round(float(d.get("conf", 0.0)), 4),
            "x1": x1, "y1": y1, "x2": x2, "y2": y2
        })
    return rows

def _write_json(json_path, image_path, dets, img_hw):
    H, W = img_hw[:2]
    payload = {"image": {"file_name": os.path.basename(image_path), "width": W, "height": H}, "detections": []}
    for d in dets:
        x1, y1, x2, y2 = d["bbox"]
        payload["detections"].append({
            "category_id": int(d.get("cls", -1)) if d.get("cls") is not None else None,
            "category_name": d.get("name"),
            "score": float(d.get("conf", 0.0)),
            "bbox_xyxy": [int(x1), int(y1), int(x2), int(y2)]
        })
    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2)

# ---------- App-ready class ----------
def _resolve_device(device: str | None, allow_cpu_fallback: bool = False) -> str:
    """
    Prefer CUDA. If CUDA requested but unavailable:
      - raise if allow_cpu_fallback is False
      - else fall back to 'cpu' with a warning.
    """
    try:
        import torch
        has_cuda = torch.cuda.is_available()
    except Exception:
        has_cuda = False

    req = (device or "cuda").strip().lower()
    if req.startswith("cuda") or req in ("cuda", "gpu", "auto"):
        if has_cuda:
            return "cuda"
        if allow_cpu_fallback:
            safe_print("[WARN] CUDA requested but not available → falling back to CPU.")
            return "cpu"
        raise RuntimeError("CUDA requested but not available. Install CUDA/PyTorch w/ CUDA or run with --device cpu.")
    # explicit cpu
    return "cpu"

class UnifiedYOLOInferencer:
    def __init__(self, weights, device=None, conf=0.25, iou=0.45, imgsz=None,
                 half="auto", agnostic_nms=False, retina_masks=True,
                 allow_cpu_fallback=False):
        # --- device (force CUDA by default) ---
        self.device = _resolve_device(device, allow_cpu_fallback=allow_cpu_fallback)

        # speed niceties
        try:
            import torch
            torch.backends.cudnn.benchmark = True
            if self.device == "cuda":
                # optional nicety for matmul perf on Ampere+
                try:
                    torch.set_float32_matmul_precision("high")
                except Exception:
                    pass
        except Exception:
            pass

        self.conf = conf
        self.iou = iou
        # may be None → we handle dynamically in predict_image
        self.imgsz = imgsz
        self.agnostic_nms = agnostic_nms
        self.retina_masks = retina_masks

        # half precision
        if half == "auto":
            self.half = (self.device.startswith("cuda"))
        else:
            self.half = bool(half)

        from ultralytics import YOLO
        self.model = YOLO(weights)
        # NOTE: passing device to predict is sufficient; some versions also allow .to on the inner model:
        try:
            m = getattr(self.model, "model", None)
            if m is not None and hasattr(m, "to"):
                m.to(self.device)
        except Exception:
            pass

        # names
        self._names = getattr(self.model.model, "names", None) or getattr(self.model, "names", None)
        safe_print(f"[YOLO] Device: {self.device} | FP16: {self.half} | RetinaMasks: {self.retina_masks}")


    def predict_image(self, image_bgr):
        """
        Returns: (detections, results_object)
        detections: list of dicts with keys: cls, name, conf, bbox, mask, keypoints

        Dynamic imgsz logic:
        - If self.imgsz is None → use current image size [H, W]
        - Else use provided imgsz (int or [h, w])
        """
        # --- dynamic imgsz when not provided ---
        H, W = image_bgr.shape[:2]
        imgsz = self.imgsz
        if imgsz is None:
            # Ultralytics expects int or list; we give [H, W]
            imgsz = [H, W]

        results = self.model.predict(
            source=image_bgr,
            conf=self.conf,
            iou=self.iou,
            imgsz=imgsz,
            half=self.half,
            agnostic_nms=self.agnostic_nms,
            retina_masks=self.retina_masks,
            verbose=False,
            device=self.device
        )
        if not results:
            return [], None
        r = results[0]
        names_map = getattr(r, "names", None) or self._names or {}
        dets = []

        boxes = getattr(r, "boxes", None)
        masks = getattr(r, "masks", None)
        if boxes is not None and len(boxes) > 0:
            xyxy = boxes.xyxy.cpu().numpy()
            conf = boxes.conf.cpu().numpy()
            cls = boxes.cls.cpu().numpy().astype(int)

            mask_arr = None
            if masks is not None and getattr(masks, "data", None) is not None:
                mask_arr = (masks.data > 0.5).cpu().numpy().astype(np.uint8)
            kps = getattr(r, "keypoints", None)
            kp_arr = None
            if kps is not None and getattr(kps, "xy", None) is not None:
                kp_arr = kps.xy.cpu().numpy()

            for i in range(len(xyxy)):
                x1, y1, x2, y2 = map(int, xyxy[i])
                c = int(cls[i])
                sc = float(conf[i])
                if isinstance(names_map, dict) and c in names_map:
                    nm = names_map[c]
                elif isinstance(names_map, list) and c < len(names_map):
                    nm = names_map[c]
                else:
                    nm = str(c)
                dets.append({
                    "cls": c, "name": str(nm), "conf": sc,
                    "bbox": [x1, y1, x2, y2],
                    "mask": mask_arr[i] if mask_arr is not None else None,
                    "keypoints": kp_arr[i] if kp_arr is not None else None
                })
            return dets, r

        # classification task
        probs = getattr(r, "probs", None)
        if probs is not None:
            c = int(getattr(probs, "top1", 0))
            sc = float(getattr(probs, "top1conf", 0.0))
            if isinstance(names_map, dict) and c in names_map:
                nm = names_map[c]
            elif isinstance(names_map, list) and c < len(names_map):
                nm = names_map[c]
            else:
                nm = str(c)
            h, w = image_bgr.shape[:2]
            dets.append({
                "cls": c, "name": str(nm), "conf": sc,
                "bbox": [0, 0, w - 1, h - 1],
                "mask": None, "keypoints": None
            })
            return dets, r

        return dets, r

    def run(self, source, out_dir, preview=False, preview_max=0,
            save_jsons=True, save_csv=True, return_rows=False):
        """
        source: folder | file | glob | video path | "0" (webcam)
        out_dir: output root; writes images/, json/, detections.csv
        """
        img_out = _ensure_dir(os.path.join(out_dir, "images"))
        json_out = _ensure_dir(os.path.join(out_dir, "json"))
        csv_path = os.path.join(out_dir, "detections.csv")
        rows = []

        is_video = str(source).isdigit() or os.path.splitext(str(source))[1].lower() in (".mp4", ".avi", ".mov", ".mkv")

        if is_video:
            cap = cv2.VideoCapture(0 if str(source).isdigit() else source)
            if not cap.isOpened():
                safe_print(f"[!] Could not open video/webcam: {source}")
                return {"csv": csv_path, "rows": rows} if return_rows else None
            idx, shown = 0, 0
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                dets, _ = self.predict_image(frame)
                vis = draw_vis(frame, dets)
                if preview and shown < preview_max:
                    shown += 1
                save_p = os.path.join(img_out, f"frame_{idx:06d}.jpg")
                cv2.imwrite(save_p, vis)
                rows.extend(_rows_from_dets(save_p, dets))
                idx += 1
            cap.release()
        else:
            files = list_media(source)
            safe_print(f"Found {len(files)} media in: {source}")
            safe_print(f" Device: {self.device} | FP16: {self.half} | RetinaMasks: {self.retina_masks}")
            shown = 0
            for i, fp in enumerate(files, 1):
                img = cv2.imread(fp)
                if img is None:
                    safe_print(f"[!] Skipping unreadable file: {fp}")
                    continue
                dets, _ = self.predict_image(img)
                vis = draw_vis(img, dets)
                save_p = os.path.join(img_out, os.path.basename(fp))
                cv2.imwrite(save_p, vis)
                safe_print(f"[ok] {i}/{len(files)} Saved: {save_p} (Detections: {len(dets)})")
                if True and shown < 0:  # preview disabled in app context
                    shown += 1
                if save_jsons:
                    jp = os.path.join(json_out, os.path.splitext(os.path.basename(fp))[0] + ".json")
                    _write_json(jp, fp, dets, img.shape)
                rows.extend(_rows_from_dets(fp, dets))

        if save_csv:
            try:
                import pandas as pd
                pd.DataFrame(rows).to_csv(csv_path, index=False)
            except Exception:
                import csv as _csv
                keys = ["image", "cls", "name", "conf", "x1", "y1", "x2", "y2"]
                with open(csv_path, "w", newline="") as f:
                    w = _csv.DictWriter(f, fieldnames=keys); w.writeheader()
                    for r in rows: w.writerow({k: r.get(k, "") for k in keys})
        safe_print(f"[🧾] CSV saved: {csv_path}")

        if return_rows:
            return {"csv": csv_path, "rows": rows}


# ===================== Detectron2 Inference Support =====================


# (reuse your helpers or keep these local)
def _ensure_dir(p):
    os.makedirs(p, exist_ok=True); return p

def _list_media_detectron(input_path):
    EXTS = (".jpg",".jpeg",".png",".bmp",".tif",".tiff",".mp4",".avi",".mov",".mkv")
    if os.path.isdir(input_path):
        files = []
        for ext in EXTS:
            files.extend(glob.glob(os.path.join(input_path, f"*{ext}")))
        files.sort()
        return files
    if os.path.isfile(input_path):
        return [input_path]
    allp = [p for p in glob.glob(input_path)]
    return [p for p in allp if os.path.splitext(p)[1].lower() in EXTS]

class UniversalDetectron2Inferencer:
    def __init__(self, weights, cfg_file=None, device=None, score_thresh=0.5, num_classes=None, fp16=False):
        import torch
        from detectron2.engine import DefaultPredictor
        from detectron2.config import get_cfg
        from detectron2 import model_zoo
        from detectron2.data import MetadataCatalog

        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.fp16 = fp16 and str(self.device).startswith("cuda")
        safe_print(f"[Device] {self.device}, FP16: {self.fp16}")

        cfg = get_cfg()
        if cfg_file is None:
            cfg_file = "COCO-InstanceSegmentation/mask_rcnn_R_50_FPN_3x.yaml"
        cfg.merge_from_file(model_zoo.get_config_file(cfg_file))
        cfg.MODEL.WEIGHTS = weights
        cfg.MODEL.DEVICE = self.device
        cfg.MODEL.ROI_HEADS.SCORE_THRESH_TEST = float(score_thresh)
        if num_classes:
            cfg.MODEL.ROI_HEADS.NUM_CLASSES = int(num_classes)

        # ---- custom metadata so boxes don't show 'person' ----
        dataset_name = "app_infer"
        if num_classes and num_classes > 1:
            classes = [f"cls_{i}" for i in range(num_classes)]
        else:
            classes = ["Dimension"]   # single class = Dimension

        MetadataCatalog.get(dataset_name).set(thing_classes=classes)
        self.metadata = MetadataCatalog.get(dataset_name)

        self.predictor = DefaultPredictor(cfg)
    

    def predict_image(self, img_bgr):
        outputs = self.predictor(img_bgr)
        inst = outputs["instances"].to("cpu")
        dets = []
        n = len(inst)
        for i in range(n):
            dets.append({
                "cls": int(inst.pred_classes[i]) if inst.has("pred_classes") else -1,
                "score": float(inst.scores[i]) if inst.has("scores") else 0.0,
                "bbox": inst.pred_boxes.tensor[i].tolist() if inst.has("pred_boxes") else [0,0,0,0]
            })
        return dets, inst

def detectron_predict_single(weights, image_path, out_dir, num_classes,
                             device=None, score_thresh=0.5, cfg_file=None):
    """
    Used by live.py:
    - runs Detectron on ONE image
    - saves overlay into out_dir/images/<filename>
    - returns (overlay_path, is_ng, score_text)
      score_text like 'BAD 0.97' or 'GOOD'
    """
    from detectron2.utils.visualizer import Visualizer, ColorMode

    img = cv2.imread(image_path)
    if img is None:
        raise RuntimeError(f"Cannot read image: {image_path}")

    infer = UniversalDetectron2Inferencer(
        weights=weights,
        cfg_file=cfg_file,
        device=device,
        score_thresh=score_thresh,
        num_classes=num_classes,
        fp16=False,
    )

    # run model
    dets, inst = infer.predict_image(img)

    # draw overlay
    vis = Visualizer(
        img[:, :, ::-1],
        metadata=infer.metadata,
        scale=1.0,
        instance_mode=ColorMode.IMAGE,
    )
    out_img = vis.draw_instance_predictions(inst).get_image()[:, :, ::-1]

    img_out = _ensure_dir(os.path.join(out_dir, "images"))
    save_p = os.path.join(img_out, os.path.basename(image_path))
    cv2.imwrite(save_p, out_img)

    if dets:
        top = max(dets, key=lambda d: d.get("score", 0.0))
        top_score = float(top.get("score", 0.0))

        # send only the numeric score as text
        score_text = f"{top_score:.2f}"

        # BAD if score < 0.98, otherwise GOOD
        is_ng = (top_score < 0.98)
    else:
        # no detections → treat as GOOD, score unknown
        score_text = "—"
        is_ng = False

    return save_p, is_ng, score_text

def detectron_infer(weights, source, out_dir, num_classes, device=None, score_thresh=0.5, cfg_file=None):
    from detectron2.utils.visualizer import Visualizer, ColorMode
    import pandas as pd

    img_out = _ensure_dir(os.path.join(out_dir, "images"))
    files = _list_media_detectron(source)
    all_rows = []

    infer = UniversalDetectron2Inferencer(
        weights=weights, cfg_file=cfg_file, device=device,
        score_thresh=score_thresh, num_classes=num_classes, fp16=False
    )

    is_webcam = str(source).isdigit()
    is_video = is_webcam or any(str(source).lower().endswith(ext) for ext in (".mp4",".avi",".mov",".mkv"))

    if is_video:
        cap = cv2.VideoCapture(0 if is_webcam else source)
        if not cap.isOpened():
            safe_print(f"[❌] Could not open video/webcam: {source}")
            return
        idx = 0
        while True:
            ok, frame = cap.read()
            if not ok: break
            dets, inst = infer.predict_image(frame)
            vis = Visualizer(frame[:, :, ::-1], metadata=infer.metadata, scale=1.0, instance_mode=ColorMode.IMAGE)
            out_img = vis.draw_instance_predictions(inst).get_image()[:, :, ::-1]
            save_p = os.path.join(img_out, f"{'webcam' if is_webcam else 'video'}_{idx:06d}.jpg")
            cv2.imwrite(save_p, out_img)
            # rows
            for j in range(len(inst)):
                bb = inst.pred_boxes.tensor[j].tolist() if inst.has("pred_boxes") else [0,0,0,0]
                sc = float(inst.scores[j]) if inst.has("scores") else 0.0
                cl = int(inst.pred_classes[j]) if inst.has("pred_classes") else -1
                all_rows.append({"image": os.path.basename(save_p), "cls": cl, "score": sc,
                                 "x1": bb[0], "y1": bb[1], "x2": bb[2], "y2": bb[3]})
            idx += 1
        cap.release()
        cv2.destroyAllWindows()
    else:
        for fp in files:
            img = cv2.imread(fp)
            if img is None:
                safe_print(f"[❌] Skipping unreadable file: {fp}")
                continue
            dets, inst = infer.predict_image(img)
            from detectron2.utils.visualizer import Visualizer, ColorMode
            vis = Visualizer(img[:, :, ::-1], metadata=infer.metadata, scale=1.0, instance_mode=ColorMode.IMAGE)
            out_img = vis.draw_instance_predictions(inst).get_image()[:, :, ::-1]
            save_p = os.path.join(img_out, os.path.basename(fp))
            cv2.imwrite(save_p, out_img)
            for j in range(len(inst)):
                bb = inst.pred_boxes.tensor[j].tolist() if inst.has("pred_boxes") else [0,0,0,0]
                sc = float(inst.scores[j]) if inst.has("scores") else 0.0
                cl = int(inst.pred_classes[j]) if inst.has("pred_classes") else -1
                all_rows.append({"image": os.path.basename(fp), "cls": cl, "score": sc,
                                 "x1": bb[0], "y1": bb[1], "x2": bb[2], "y2": bb[3]})

    if all_rows:
        csv_path = os.path.join(out_dir, "detections.csv")
        pd.DataFrame(all_rows).to_csv(csv_path, index=False)
        safe_print(f"CSV saved: {csv_path}")
    safe_print(f"[OK] All outputs saved in → {out_dir}")

# ------------------------------ CLI ------------------------------

def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="Unified inference launcher")
    p.add_argument("--backend", choices=["yolo", "detectron"], default="yolo")

    # shared
    p.add_argument("--weights", required=True)
    p.add_argument("--source", required=True)
    p.add_argument("--out_dir", required=True)

    # YOLO defaults (kept, but not shown in GUI)
    p.add_argument("--device", default=None)
    p.add_argument("--conf", type=float, default=0.20)
    p.add_argument("--iou", type=float, default=0.50)
    p.add_argument("--imgsz", type=int, default=1024)
    p.add_argument("--half", default="auto")
    p.add_argument("--no-retina_masks", dest="retina_masks", action="store_false")
    p.set_defaults(retina_masks=True)

    # Detectron only
    p.add_argument("--num_classes", type=int, default=None)
    p.add_argument("--score_thresh", type=float, default=0.5)
    p.add_argument("--cfg_file", default=None)
    return p.parse_args(argv)


def _to_bool_half(x: str):
    if x is None:
        return "auto"
    x = str(x).strip().lower()
    if x in ("auto",):
        return "auto"
    return x in ("1", "true", "yes", "y")

def main(argv=None):
    args = _parse_args(argv)
    os.makedirs(args.out_dir, exist_ok=True)

    if args.backend == "yolo":
        half_val = _to_bool_half(args.half)
        infer = UnifiedYOLOInferencer(
            weights=args.weights,
            device=args.device,
            conf=args.conf, iou=args.iou, imgsz=args.imgsz,
            half=half_val, agnostic_nms=False, retina_masks=bool(args.retina_masks)
        )
        infer.run(
            source=args.source,
            out_dir=args.out_dir,
            preview=False, preview_max=0,
            save_jsons=True, save_csv=True, return_rows=False
        )
    else:
        if args.num_classes is None or args.num_classes <= 0:
            safe_print("[ERROR] --num_classes must be provided for Detectron backend.")
            sys.exit(2)
        detectron_infer(
            weights=args.weights,
            source=args.source,
            out_dir=args.out_dir,
            num_classes=int(args.num_classes),
            device=None,                 # AUTO (as requested)
            score_thresh=args.score_thresh,
            cfg_file=args.cfg_file
        )


if __name__ == "__main__":
    main()
