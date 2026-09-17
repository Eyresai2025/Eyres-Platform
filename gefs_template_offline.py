# gefs_template_offline.py

import os
import numpy as np
import cv2

# ---- Optional GPU support via PyTorch ----
try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False


# =====================================================================
#                      CPU UTILITIES (NumPy)
# =====================================================================

def normalize_block(block: np.ndarray) -> np.ndarray:
    """Normalize a block of pixel values to [0, 1]."""
    block = block.astype(np.float32)
    return block / 255.0


def find_gefs_cpu(fuzzy_relation: np.ndarray) -> np.ndarray:
    """Greatest Eigen Fuzzy Set (CPU / NumPy)."""
    A_prev = np.max(fuzzy_relation, axis=0)
    while True:
        A_next = np.zeros_like(A_prev)
        for y in range(A_prev.shape[0]):
            A_next[y] = np.max(np.minimum(A_prev, fuzzy_relation[:, y]))
        if np.allclose(A_prev, A_next):
            break
        A_prev = A_next
    return A_next


def find_sefs_cpu(fuzzy_relation: np.ndarray) -> np.ndarray:
    """Smallest Eigen Fuzzy Set (CPU / NumPy)."""
    B_prev = np.min(fuzzy_relation, axis=1)
    while True:
        B_next = np.zeros_like(B_prev)
        for y in range(B_prev.shape[0]):
            B_next[y] = np.min(np.maximum(B_prev, fuzzy_relation[:, y]))
        if np.allclose(B_prev, B_next):
            break
        B_prev = B_next
    return B_next


def compute_similarity_cpu(block1_norm: np.ndarray, block2_norm: np.ndarray) -> float:
    """
    GEFS + SEFS similarity, CPU version (NumPy).
    block1_norm, block2_norm must already be normalized to [0, 1].
    """
    b1 = block1_norm.flatten()
    b2 = block2_norm.flatten()

    fuzzy_relation1 = np.outer(b1, b1)
    fuzzy_relation2 = np.outer(b2, b2)

    gefs1 = find_gefs_cpu(fuzzy_relation1)
    sefs1 = find_sefs_cpu(fuzzy_relation1)
    gefs2 = find_gefs_cpu(fuzzy_relation2)
    sefs2 = find_sefs_cpu(fuzzy_relation2)

    n = block1_norm.shape[0]

    gefs_diff_squared = (gefs1 - gefs2) ** 2
    gefs_sum_diff_squared = np.sum(gefs_diff_squared)
    gefs_normalized_distance = np.sqrt(gefs_sum_diff_squared) / (n ** 2)

    sefs_diff_squared = (sefs1 - sefs2) ** 2
    sefs_sum_diff_squared = np.sum(sefs_diff_squared)
    sefs_normalized_distance = np.sqrt(sefs_sum_diff_squared) / (n ** 2)

    combined_distance = gefs_normalized_distance + sefs_normalized_distance
    similarity = 1.0 - combined_distance / (2.0 * block1_norm.size)
    return float(similarity)


# =====================================================================
#                      GPU UTILITIES (PyTorch)
# =====================================================================

def find_gefs_torch(fuzzy_relation: "torch.Tensor") -> "torch.Tensor":
    """
    Greatest Eigen Fuzzy Set on GPU/CPU using PyTorch.
    fuzzy_relation: (N, N) tensor.
    """
    A_prev = fuzzy_relation.max(dim=0).values  # (N,)
    while True:
        # A_next[y] = max_x min(A_prev[x], fuzzy_relation[x, y])
        A_next = torch.min(A_prev.view(-1, 1), fuzzy_relation).max(dim=0).values
        if torch.allclose(A_prev, A_next):
            break
        A_prev = A_next
    return A_next


def find_sefs_torch(fuzzy_relation: "torch.Tensor") -> "torch.Tensor":
    """
    Smallest Eigen Fuzzy Set on GPU/CPU using PyTorch.
    fuzzy_relation: (N, N) tensor.
    """
    B_prev = fuzzy_relation.min(dim=1).values  # (N,)
    while True:
        # B_next[y] = min_x max(B_prev[x], fuzzy_relation[x, y])
        B_next = torch.max(B_prev.view(-1, 1), fuzzy_relation).min(dim=0).values
        if torch.allclose(B_prev, B_next):
            break
        B_prev = B_next
    return B_next


def compute_similarity_torch(block1_norm: "torch.Tensor",
                             block2_norm: "torch.Tensor") -> float:
    """
    GEFS + SEFS similarity using PyTorch (can be on GPU).
    block1_norm, block2_norm: 2D tensors, already normalized [0, 1].
    """
    b1 = block1_norm.reshape(-1)  # (N,)
    b2 = block2_norm.reshape(-1)

    fuzzy_relation1 = torch.outer(b1, b1)  # (N, N)
    fuzzy_relation2 = torch.outer(b2, b2)

    gefs1 = find_gefs_torch(fuzzy_relation1)
    sefs1 = find_sefs_torch(fuzzy_relation1)
    gefs2 = find_gefs_torch(fuzzy_relation2)
    sefs2 = find_sefs_torch(fuzzy_relation2)

    n = block1_norm.shape[0]

    gefs_diff_squared = (gefs1 - gefs2) ** 2
    gefs_sum_diff_squared = gefs_diff_squared.sum()
    gefs_normalized_distance = torch.sqrt(gefs_sum_diff_squared) / (n ** 2)

    sefs_diff_squared = (sefs1 - sefs2) ** 2
    sefs_sum_diff_squared = sefs_diff_squared.sum()
    sefs_normalized_distance = torch.sqrt(sefs_sum_diff_squared) / (n ** 2)

    combined_distance = gefs_normalized_distance + sefs_normalized_distance
    similarity = 1.0 - combined_distance / (2.0 * block1_norm.numel())

    return float(similarity.item())


# =====================================================================
#                FULL CPU IMPLEMENTATION (OVERLAY + META)
# =====================================================================

def _run_template_cpu(
    good_img_path: str,
    bad_img_path: str,
    threshold: float,
    save_only_bad: bool,
):
    # --- load and resize images ---
    img1 = cv2.imread(good_img_path, cv2.IMREAD_GRAYSCALE)
    img2 = cv2.imread(bad_img_path, cv2.IMREAD_GRAYSCALE)

    if img1 is None:
        raise RuntimeError(f"Cannot read GOOD image: {good_img_path}")
    if img2 is None:
        raise RuntimeError(f"Cannot read BAD image: {bad_img_path}")

    img1 = cv2.resize(img1, (1024, 1024), interpolation=cv2.INTER_AREA)
    img2 = cv2.resize(img2, (1024, 1024), interpolation=cv2.INTER_AREA)

    # colored version for overlay
    overlay = cv2.cvtColor(img2, cv2.COLOR_GRAY2BGR)

    h, w = img1.shape
    assert h == 1024 and w == 1024, "Internal assumption: 1024x1024"

    large_block_height = h // 2     # 512
    large_block_width  = w // 4     # 256
    sub_block_height   = large_block_height // 8   # 64
    sub_block_width    = large_block_width  // 8   # 32

    large_block_similarities = []

    # There are 2x4 = 8 large blocks
    for lb_idx in range(8):
        lb_row = lb_idx // 4
        lb_col = lb_idx % 4
        i0 = lb_row * large_block_height
        j0 = lb_col * large_block_width

        sub_sims = []

        # each large block has 8x8 = 64 sub-blocks
        for sb_row in range(8):
            for sb_col in range(8):
                r0 = sb_row * sub_block_height
                c0 = sb_col * sub_block_width
                r1 = r0 + sub_block_height
                c1 = c0 + sub_block_width

                # global positions in the full image
                gr0 = i0 + r0
                gc0 = j0 + c0
                gr1 = i0 + r1
                gc1 = j0 + c1

                sb1 = img1[gr0:gr1, gc0:gc1]
                sb2 = img2[gr0:gr1, gc0:gc1]

                sb1_norm = normalize_block(sb1)
                sb2_norm = normalize_block(sb2)

                sim = compute_similarity_cpu(sb1_norm, sb2_norm)
                sub_sims.append(sim)

                if sim <= threshold:
                    # darken + red overlay
                    overlay[gr0:gr1, gc0:gc1, :] = overlay[gr0:gr1, gc0:gc1, :] * 0.3
                    overlay[gr0:gr1, gc0:gc1, 2] = 255

        block_sim = float(np.mean(sub_sims))
        large_block_similarities.append(block_sim)

    overall_similarity = float(np.mean(large_block_similarities))

    is_bad = overall_similarity <= threshold
    decision = "BAD" if is_bad else "GOOD"

    base_dir = os.path.dirname(bad_img_path)
    base_name = os.path.splitext(os.path.basename(bad_img_path))[0]

    overlay_path = None

    if (not save_only_bad) or is_bad:
        overlay_name = f"{base_name}_gefs_overlay.png"
        overlay_path = os.path.join(base_dir, overlay_name)
        cv2.imwrite(overlay_path, overlay)

        # ---- META file with full info ----
        meta_name = f"{base_name}_gefs_meta.txt"
        meta_path = os.path.join(base_dir, meta_name)
        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                f.write(f"GOOD_IMAGE={good_img_path}\n")
                f.write(f"BAD_IMAGE={bad_img_path}\n")
                f.write(f"OVERLAY_IMAGE={overlay_path}\n")
                f.write(f"THRESHOLD={threshold:.10f}\n")
                f.write(f"OVERALL_SIMILARITY={overall_similarity:.10f}\n")
                f.write(f"DECISION={decision}\n")
                f.write(f"IS_BAD={int(is_bad)}\n")
        except Exception as e:
            print("[GEFS] failed to write meta file:", e)

    return overall_similarity, overlay_path, decision


# =====================================================================
#              FULL GPU IMPLEMENTATION (PyTorch + OpenCV)
# =====================================================================
def _run_template_torch(
    good_img_path: str,
    bad_img_path: str,
    threshold: float,
    save_only_bad: bool,
    device: str | None = None,
):
    """
    Full GEFS/SEFS template matching using PyTorch for similarity,
    but overlay drawing stays in NumPy/OpenCV.

    Returns:
        overall_similarity (float),
        overlay_path (str or None),
        decision ("GOOD" or "BAD")
    """
    if not TORCH_AVAILABLE:
        raise RuntimeError("PyTorch is not available, cannot use GPU path.")

    import torch  # local import to avoid issues if TORCH_AVAILABLE is False

    # -------- 1. Load & resize images (same as CPU) --------
    img1 = cv2.imread(good_img_path, cv2.IMREAD_GRAYSCALE)
    img2 = cv2.imread(bad_img_path, cv2.IMREAD_GRAYSCALE)

    if img1 is None:
        raise RuntimeError(f"Cannot read GOOD image: {good_img_path}")
    if img2 is None:
        raise RuntimeError(f"Cannot read BAD image: {bad_img_path}")

    img1 = cv2.resize(img1, (1024, 1024), interpolation=cv2.INTER_AREA)
    img2 = cv2.resize(img2, (1024, 1024), interpolation=cv2.INTER_AREA)

    # coloured version for overlay (we do highlighting here)
    overlay = cv2.cvtColor(img2, cv2.COLOR_GRAY2BGR)

    h, w = img1.shape
    if h != 1024 or w != 1024:
        raise RuntimeError("Internal assumption: images must be 1024x1024 after resize.")

    # -------- 2. Move normalized images to torch device --------
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    # tensors normalized to [0, 1]
    t1 = torch.from_numpy(img1).float().to(device) / 255.0
    t2 = torch.from_numpy(img2).float().to(device) / 255.0

    # -------- 3. Same block structure as CPU version --------
    large_block_height = h // 2       # 512
    large_block_width  = w // 4       # 256
    sub_block_height   = large_block_height // 8   # 64
    sub_block_width    = large_block_width  // 8   # 32

    large_block_similarities = []

    # There are 2 x 4 = 8 large blocks
    for lb_idx in range(8):
        lb_row = lb_idx // 4
        lb_col = lb_idx % 4
        i0 = lb_row * large_block_height
        j0 = lb_col * large_block_width

        sub_sims = []

        # Each large block has 8 x 8 = 64 sub-blocks
        for sb_row in range(8):
            for sb_col in range(8):
                r0 = sb_row * sub_block_height
                c0 = sb_col * sub_block_width
                r1 = r0 + sub_block_height
                c1 = c0 + sub_block_width

                # global positions in full image
                gr0 = i0 + r0
                gc0 = j0 + c0
                gr1 = i0 + r1
                gc1 = j0 + c1

                # slice from torch tensors (already normalized)
                sb1 = t1[gr0:gr1, gc0:gc1]
                sb2 = t2[gr0:gr1, gc0:gc1]

                sim = compute_similarity_torch(sb1, sb2)
                sub_sims.append(sim)

                # Overlay on NumPy image when similarity <= threshold
                if sim <= threshold:
                    # darken + red overlay
                    overlay[gr0:gr1, gc0:gc1, :] = overlay[gr0:gr1, gc0:gc1, :] * 0.3
                    overlay[gr0:gr1, gc0:gc1, 2] = 255

        block_sim = float(np.mean(sub_sims))
        large_block_similarities.append(block_sim)

    overall_similarity = float(np.mean(large_block_similarities))

    # -------- 4. Decision + writing overlay & meta --------
    is_bad = overall_similarity <= threshold
    decision = "BAD" if is_bad else "GOOD"

    base_dir = os.path.dirname(bad_img_path)
    base_name = os.path.splitext(os.path.basename(bad_img_path))[0]

    overlay_path = None

    if (not save_only_bad) or is_bad:
        overlay_name = f"{base_name}_gefs_overlay.png"
        overlay_path = os.path.join(base_dir, overlay_name)
        cv2.imwrite(overlay_path, overlay)

        # META FILE (same format as CPU path)
        meta_name = f"{base_name}_gefs_meta.txt"
        meta_path = os.path.join(base_dir, meta_name)
        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                f.write(f"GOOD_IMAGE={good_img_path}\n")
                f.write(f"BAD_IMAGE={bad_img_path}\n")
                f.write(f"OVERLAY_IMAGE={overlay_path}\n")
                f.write(f"THRESHOLD={threshold:.10f}\n")
                f.write(f"OVERALL_SIMILARITY={overall_similarity:.10f}\n")
                f.write(f"DECISION={decision}\n")
                f.write(f"IS_BAD={int(is_bad)}\n")
        except Exception as e:
            print("[GEFS] (torch) failed to write meta file:", e)

    return overall_similarity, overlay_path, decision



# =====================================================================
#                       PUBLIC API (WRAPPER)
# =====================================================================

def run_good_bad_template_matching(
    good_img_path: str,
    bad_img_path: str,
    threshold: float,
    save_only_bad: bool = False,
    prefer_gpu: bool = True,
):
    """
    High-level entry used by live.py.

    Chooses Torch (GPU) path if available and prefer_gpu=True,
    otherwise falls back to the pure NumPy CPU implementation.

    Args
    ----
    good_img_path : str
        Path to GOOD reference image.
    bad_img_path  : str
        Path to BAD / test image.
    threshold     : float
        Similarity threshold. Blocks with similarity <= threshold are treated as defect.
    save_only_bad : bool, optional
        If True, overlay is written only when decision is BAD.
        If False, overlay is always written.
    prefer_gpu    : bool, optional
        If True and PyTorch+CUDA are available, use GPU path.

    Returns
    -------
    overall_similarity : float
    overlay_path       : str or None
    decision           : "GOOD" or "BAD"
    """
    # Try Torch path first (if allowed and available)
    if prefer_gpu and TORCH_AVAILABLE:
        try:
            return _run_template_torch(
                good_img_path=good_img_path,
                bad_img_path=bad_img_path,
                threshold=threshold,
                save_only_bad=save_only_bad,
            )
        except Exception as e:
            print("[GEFS] Torch path failed, falling back to CPU:", e)

    # Fallback: pure NumPy path
    return _run_template_cpu(
        good_img_path=good_img_path,
        bad_img_path=bad_img_path,
        threshold=threshold,
        save_only_bad=save_only_bad,
    )
