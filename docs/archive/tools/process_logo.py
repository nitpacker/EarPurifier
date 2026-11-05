"""
Logo Processing & Frame Removal Pipeline for cleanerEARS / EarPurifier
Preserves 100% original quality, scale, and color fidelity.
Defringes anti-aliased edges and provides both isolated icons and transparent marks.
"""

from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw


def process_logo(assets_dir: Path):
    orig_path = assets_dir / "logo.png"
    if not orig_path.exists():
        raise FileNotFoundError(f"Original logo not found at {orig_path}")

    orig = Image.open(orig_path).convert("RGBA")
    orig_arr = np.array(orig, dtype=np.float32)
    w, h = orig.size

    # Exact squircle geometry identified from original artwork
    left = 12.5
    right = 497.5
    top = 0.0
    bottom = 480.5
    r_top = 104.0
    r_bot = 108.0

    # Pale cyan background frame color to defringe against
    bg_color = np.array([228.0, 243.0, 238.0], dtype=np.float32)

    def create_squircle_mask(width, height, l, t, r, b, rad_top, rad_bot, scale=8):
        mask_hi = Image.new("L", (width * scale, height * scale), 0)
        draw = ImageDraw.Draw(mask_hi)
        rad_avg = int(round((rad_top + rad_bot) / 2.0 * scale))
        draw.rounded_rectangle([l * scale, t * scale, r * scale, b * scale], radius=rad_avg, fill=255)
        mask = mask_hi.resize((width, height), Image.Resampling.LANCZOS)
        return np.array(mask, dtype=np.float32) / 255.0

    # 1. Unshifted Squircle (Frame removed, original coordinate alignment)
    mask_unshifted = create_squircle_mask(w, h, left, top, right, bottom, r_top, r_bot)
    out_unshifted = np.zeros_like(orig_arr)
    alpha_u = mask_unshifted[:, :, None]
    safe_alpha_u = np.maximum(alpha_u, 0.05)
    defringed_u = (orig_arr[:, :, :3] - (1.0 - alpha_u) * bg_color) / safe_alpha_u
    defringed_u = np.clip(defringed_u, 0, 255)
    defringed_u = np.where(alpha_u >= 0.99, orig_arr[:, :, :3], defringed_u)
    out_unshifted[:, :, :3] = defringed_u
    out_unshifted[:, :, 3] = np.clip(mask_unshifted * 255.0, 0, 255)
    img_unshifted = Image.fromarray(out_unshifted.astype(np.uint8), "RGBA")
    img_unshifted.save(assets_dir / "logo_clean_unshifted.png", "PNG")

    # 2. Centered Squircle (512x512 standard canvas, perfectly balanced margins)
    shift_y = 16  # Integer shift guarantees 100% bit-for-bit lossless copying
    mask_centered = create_squircle_mask(w, h, left, top + shift_y, right, bottom + shift_y, r_top, r_bot)
    src_h = 481
    orig_shifted = np.zeros_like(orig_arr)
    orig_shifted[shift_y:shift_y + src_h, :] = orig_arr[0:src_h, :]
    out_centered = np.zeros_like(orig_arr)
    alpha_c = mask_centered[:, :, None]
    safe_alpha_c = np.maximum(alpha_c, 0.05)
    defringed_c = (orig_shifted[:, :, :3] - (1.0 - alpha_c) * bg_color) / safe_alpha_c
    defringed_c = np.clip(defringed_c, 0, 255)
    defringed_c = np.where(alpha_c >= 0.99, orig_shifted[:, :, :3], defringed_c)
    out_centered[:, :, :3] = defringed_c
    out_centered[:, :, 3] = np.clip(mask_centered * 255.0, 0, 255)
    img_centered = Image.fromarray(out_centered.astype(np.uint8), "RGBA")
    img_centered.save(assets_dir / "logo_clean.png", "PNG")

    # 3. Tight Bounding Box (486x481)
    tight_crop = img_unshifted.crop((12, 0, 498, 481))
    tight_crop.save(assets_dir / "logo_tight.png", "PNG")

    # 4. Multi-resolution Windows ICO
    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    img_centered.save(assets_dir / "logo_clean.ico", format="ICO", sizes=ico_sizes)

    # 5. Isolated Transparent Mark (Sprout + Wave Ribbon without green background)
    bg_pts = []
    for y in range(512):
        for x in range(512):
            if 20 <= y <= 80 and ((50 <= x <= 180) or (330 <= x <= 460)):
                bg_pts.append((x, y, orig_arr[y, x, 0], orig_arr[y, x, 1], orig_arr[y, x, 2]))
            elif 400 <= y <= 460 and 80 <= x <= 430:
                bg_pts.append((x, y, orig_arr[y, x, 0], orig_arr[y, x, 1], orig_arr[y, x, 2]))
            elif (140 <= y <= 240 or 320 <= y <= 380) and (25 <= x <= 75 or 435 <= x <= 485):
                bg_pts.append((x, y, orig_arr[y, x, 0], orig_arr[y, x, 1], orig_arr[y, x, 2]))

    bg_pts = np.array(bg_pts, dtype=float)
    X = np.column_stack([
        np.ones(len(bg_pts)),
        bg_pts[:, 0],
        bg_pts[:, 1],
        bg_pts[:, 0] ** 2,
        bg_pts[:, 0] * bg_pts[:, 1],
        bg_pts[:, 1] ** 2,
    ])
    cR, _, _, _ = np.linalg.lstsq(X, bg_pts[:, 2], rcond=None)
    cG, _, _, _ = np.linalg.lstsq(X, bg_pts[:, 3], rcond=None)
    cB, _, _, _ = np.linalg.lstsq(X, bg_pts[:, 4], rcond=None)

    grid_y, grid_x = np.mgrid[0:512, 0:512]
    X_all = np.column_stack([
        np.ones(512 * 512),
        grid_x.ravel(),
        grid_y.ravel(),
        grid_x.ravel() ** 2,
        grid_x.ravel() * grid_y.ravel(),
        grid_y.ravel() ** 2,
    ])
    pred_R = (X_all @ cR).reshape((512, 512))
    pred_G = (X_all @ cG).reshape((512, 512))
    pred_B = (X_all @ cB).reshape((512, 512))
    pred_bg = np.stack([pred_R, pred_G, pred_B], axis=2)

    diff = np.linalg.norm(orig_arr[:, :, :3] - pred_bg, axis=2)
    lum_diff = np.mean(orig_arr[:, :, :3] - pred_bg, axis=2)

    artwork_region = (grid_x >= 18) & (grid_x <= 492) & (grid_y >= 100) & (grid_y <= 375)
    plant_region = (grid_x >= 140) & (grid_x <= 360) & (grid_y >= 100) & (grid_y <= 270)
    plant_diff = diff * plant_region
    plant_alpha = np.clip((plant_diff - 12.0) / 18.0, 0, 1.0)

    wave_region = artwork_region & (grid_y >= 215)
    wave_diff = np.maximum(0, lum_diff) * wave_region
    wave_alpha = np.clip((wave_diff - 5.0) / 20.0, 0, 1.0)
    wave_color_alpha = np.clip((diff * wave_region - 14.0) / 22.0, 0, 1.0)

    total_alpha = np.maximum(plant_alpha, np.maximum(wave_alpha, wave_color_alpha))
    left_taper = np.clip((grid_x - 18.0) / 16.0, 0, 1.0)
    right_taper = np.clip((492.0 - grid_x) / 16.0, 0, 1.0)
    horiz_taper = np.minimum(left_taper, right_taper)
    total_alpha = total_alpha * horiz_taper

    safe_a = np.maximum(total_alpha[:, :, None], 0.1)
    defringed_fg = (orig_arr[:, :, :3] - (1.0 - total_alpha[:, :, None]) * pred_bg) / safe_a
    defringed_fg = np.clip(defringed_fg, 0, 255)
    fg_rgb = np.where(total_alpha[:, :, None] >= 0.95, orig_arr[:, :, :3], defringed_fg)

    out_trans = np.zeros((512, 512, 4), dtype=np.uint8)
    out_trans[:, :, :3] = np.clip(fg_rgb, 0, 255).astype(np.uint8)
    out_trans[:, :, 3] = np.clip(total_alpha * 255.0, 0, 255).astype(np.uint8)
    img_trans = Image.fromarray(out_trans, "RGBA")
    img_trans.save(assets_dir / "logo_transparent.png", "PNG")


if __name__ == "__main__":
    process_logo(Path("assets"))
    print("Logo processing completed successfully.")
