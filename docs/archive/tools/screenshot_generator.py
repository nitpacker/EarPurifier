"""
EarPurifier User Guide - Automated Screenshot Production Suite.
Runs the actual PySide6 application code and dialogs, injecting realistic
neutral documentary metadata, and capturing high-resolution screenshots
for BOTH Arabic (RTL) and English (LTR).
"""

import os
import sys
from PySide6.QtWidgets import (
    QApplication, QWidget, QDialog
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont, QPen

# Ensure clean imports from cleanerEARS
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config_manager import ConfigManager
from queue_manager import QueueManager
from dependency_manager import DependencyManager
from i18n import set_language, apply_app_direction, t
from ui.theme import Theme, ThemeMode
from ui.main_window import MainWindow
from ui.dialogs import (
    SettingsDialog, AudioTrackSelectDialog,
    DeleteConfirmDialog, PhoneVerificationWarningDialog
)
from ui.overlay_widgets import DownloadOverlayWidget

OUTPUT_DIR = r"..path..to..docs\assets\screenshots"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def capture_widget(widget: QWidget, filename: str):
    """Captures a QWidget or QDialog to a PNG file."""
    widget.adjustSize()
    QApplication.processEvents()
    pix = widget.grab()
    dest = os.path.join(OUTPUT_DIR, filename)
    pix.save(dest)
    print(f"Captured screenshot: {filename} ({pix.width()}x{pix.height()})")

def main():
    app = QApplication.instance() or QApplication(sys.argv)

    config = ConfigManager()

    # Prevent background threads and network calls during screenshot generation
    MainWindow.init_threads = lambda self: None
    MainWindow.start_auto_update_check = lambda self: None

    # 1. Main Window: Arabic Light & Dark
    config.set("language", "ar")
    set_language("ar")
    apply_app_direction(app, "ar")
    Theme.set_mode(ThemeMode.LIGHT)

    win = MainWindow()
    win.resize(1020, 700)
    win.show()
    QApplication.processEvents()

    # Capture Arabic - Light & Dark
    capture_widget(win, "main-window-ar-light.png")
    win.apply_theme(ThemeMode.DARK)
    QApplication.processEvents()
    capture_widget(win, "main-window-ar-dark.png")

    # 2. Main Window: English Light & Dark
    win.apply_language("en")
    win.apply_theme(ThemeMode.LIGHT)
    QApplication.processEvents()
    capture_widget(win, "main-window-en-light.png")

    win.apply_theme(ThemeMode.DARK)
    QApplication.processEvents()
    capture_widget(win, "main-window-en-dark.png")

    # ══════════════════════════════════════════════════════
    # 3. ARABIC JOURNEYS & CARDS
    # ══════════════════════════════════════════════════════
    win.apply_language("ar")
    win.apply_theme(ThemeMode.LIGHT)
    win.switch_view(0)
    sec_cloud = win.cloud_section

    job_ar1 = {
        "id": "job-1",
        "original_media": r"C:\Media\وثائقي_أنهار_الطبيعة.mp4",
        "mode": "Cloud (Kaggle)",
        "duration": 720.0,
        "model": "Band-Split RoFormer (HQ Vocal/Instrumental)",
        "selected_audio_stream": 0,
        "status": "COMPLETED",
        "message": "اكتملت المعالجة · تمت إزالة الموسيقى بنجاح",
        "error_message": "",
        "started_at": "2026-11-05T01:00:00+00:00",
        "added_at": "2026-11-05T00:58:00+00:00",
        "final_elapsed_seconds": 185,
        "output_media": r"C:\Output\وثائقي_أنهار_الطبيعة_purified.mp4"
    }

    job_ar2 = {
        "id": "job-2",
        "original_media": r"C:\Media\وثائقي_أعماق_المحيطات.mp4",
        "mode": "Cloud (Kaggle)",
        "duration": 1420.0,
        "model": "Band-Split RoFormer (HQ Vocal/Instrumental)",
        "selected_audio_stream": 0,
        "status": "PROCESSING_CLOUD",
        "message": "المرحلة 3/5: معالجة الذكاء الاصطناعي على السحابة... 58٪",
        "error_message": "",
        "started_at": "2026-11-05T01:10:00+00:00",
        "added_at": "2026-11-05T01:08:00+00:00",
        "output_media": ""
    }

    job_ar3 = {
        "id": "job-3",
        "original_media": r"C:\Media\وثائقي_حضارات_قديمة.mkv",
        "mode": "Cloud (Kaggle)",
        "duration": 650.0,
        "model": "MDX23C (Fast Vocal/Instrumental)",
        "selected_audio_stream": 0,
        "status": "UPLOADING",
        "message": "المرحلة 2/5: جارٍ رفع ملف الصوت إلى خادم المعالجة...",
        "error_message": "",
        "started_at": "2026-11-05T01:12:00+00:00",
        "added_at": "2026-11-05T01:11:00+00:00",
        "output_media": ""
    }

    job_ar4 = {
        "id": "job-4",
        "original_media": r"C:\Media\تسجيل_كوكب_الأرض_الصوتي.flac",
        "mode": "Cloud (Kaggle)",
        "duration": 310.0,
        "model": "Kim Vocal 2 (Ultra Fast)",
        "selected_audio_stream": 0,
        "status": "EXTRACTING",
        "message": "المرحلة 1/5: جارٍ استخراج المسار الصوتي الأصلي بدقة...",
        "error_message": "",
        "started_at": "2026-11-05T01:14:00+00:00",
        "added_at": "2026-11-05T01:13:00+00:00",
        "output_media": ""
    }

    sec_cloud.queue_manager.state["jobs"] = {
        "job-1": job_ar1,
        "job-2": job_ar2,
        "job-3": job_ar3,
        "job-4": job_ar4
    }
    sec_cloud.refresh_list()
    QApplication.processEvents()

    w2 = sec_cloud.job_widgets.get("job-2")
    if w2:
        w2.progress.setRange(0, 100)
        w2.progress.setValue(58)
        w2.lbl_eta.setVisible(True)
        w2.lbl_eta.setText("الوقت التقديري المتبقي: ~1 د 40 ث")

    w3 = sec_cloud.job_widgets.get("job-3")
    if w3:
        w3.progress.setRange(0, 100)
        w3.progress.setValue(25)
        w3.lbl_eta.setVisible(True)
        w3.lbl_eta.setText("جارٍ الرفع...")

    QApplication.processEvents()
    capture_widget(win, "cloud-journey-active.png")
    capture_widget(win, "cloud-journey-active-ar.png")

    if w1 := sec_cloud.job_widgets.get("job-1"):
        capture_widget(w1, "job-card-completed.png")
        capture_widget(w1, "job-card-completed-ar.png")
    if w2:
        capture_widget(w2, "job-card-processing.png")
        capture_widget(w2, "job-card-processing-ar.png")

    # Arabic Local Journey
    win.switch_view(1)
    sec_local = win.local_section

    job_lar1 = {
        "id": "job-l1",
        "original_media": r"C:\Media\وثائقي_عالم_النباتات.mp4",
        "mode": "Local (GPU)",
        "duration": 940.0,
        "model": "Band-Split RoFormer (HQ Vocal/Instrumental)",
        "selected_audio_stream": 0,
        "status": "PROCESSING_LOCAL",
        "message": "جارٍ معالجة الصوت محليًا... 68٪",
        "error_message": "",
        "started_at": "2026-11-05T01:20:00+00:00",
        "added_at": "2026-11-05T01:19:00+00:00",
        "output_media": ""
    }

    job_lar2 = {
        "id": "job-l2",
        "original_media": r"C:\Media\تسجيل_الفضاء_الوثائقي.wav",
        "mode": "Local (GPU)",
        "duration": 480.0,
        "model": "Kim Vocal 2 (Ultra Fast)",
        "selected_audio_stream": 0,
        "status": "COMPLETED",
        "message": "اكتملت المهمة · تمت إزالة الموسيقى بنجاح",
        "error_message": "",
        "started_at": "2026-11-05T01:15:00+00:00",
        "added_at": "2026-11-05T01:14:00+00:00",
        "final_elapsed_seconds": 64,
        "output_media": r"C:\Output\تسجيل_الفضاء_الوثائقي_purified.wav"
    }

    sec_local.queue_manager.state["jobs"] = {"job-l1": job_lar1, "job-l2": job_lar2}
    sec_local.refresh_list()
    QApplication.processEvents()

    wl1 = sec_local.job_widgets.get("job-l1")
    if wl1:
        wl1.progress.setRange(0, 100)
        wl1.progress.setValue(68)
        wl1.lbl_eta.setVisible(True)
        wl1.lbl_eta.setText("الوقت المتبقي: ~2 د 15 ث")

    QApplication.processEvents()
    capture_widget(win, "local-journey-active.png")
    capture_widget(win, "local-journey-active-ar.png")

    # ══════════════════════════════════════════════════════
    # 4. ENGLISH JOURNEYS & CARDS (Pure English UI)
    # ══════════════════════════════════════════════════════
    win.apply_language("en")
    win.apply_theme(ThemeMode.LIGHT)
    win.switch_view(0)
    sec_cloud_en = win.cloud_section

    job_en1 = {
        "id": "job-en-1",
        "original_media": r"C:\Media\Nature_Rivers_Documentary.mp4",
        "mode": "Cloud (Kaggle)",
        "duration": 720.0,
        "model": "Band-Split RoFormer (HQ Vocal/Instrumental)",
        "selected_audio_stream": 0,
        "status": "COMPLETED",
        "message": "Purification Complete · Music removed successfully",
        "error_message": "",
        "started_at": "2026-11-05T01:00:00+00:00",
        "added_at": "2026-11-05T00:58:00+00:00",
        "final_elapsed_seconds": 185,
        "output_media": r"C:\Output\Nature_Rivers_Documentary_purified.mp4"
    }

    job_en2 = {
        "id": "job-en-2",
        "original_media": r"C:\Media\Ocean_Depths_Documentary.mp4",
        "mode": "Cloud (Kaggle)",
        "duration": 1420.0,
        "model": "Band-Split RoFormer (HQ Vocal/Instrumental)",
        "selected_audio_stream": 0,
        "status": "PROCESSING_CLOUD",
        "message": "Stage 3/5: AI Separation on Cloud... 58%",
        "error_message": "",
        "started_at": "2026-11-05T01:10:00+00:00",
        "added_at": "2026-11-05T01:08:00+00:00",
        "output_media": ""
    }

    job_en3 = {
        "id": "job-en-3",
        "original_media": r"C:\Media\Ancient_Civilizations.mkv",
        "mode": "Cloud (Kaggle)",
        "duration": 650.0,
        "model": "MDX23C (Fast Vocal/Instrumental)",
        "selected_audio_stream": 0,
        "status": "UPLOADING",
        "message": "Stage 2/5: Uploading audio stream to cloud...",
        "error_message": "",
        "started_at": "2026-11-05T01:12:00+00:00",
        "added_at": "2026-11-05T01:11:00+00:00",
        "output_media": ""
    }

    job_en4 = {
        "id": "job-en-4",
        "original_media": r"C:\Media\Planet_Earth_Audio.flac",
        "mode": "Cloud (Kaggle)",
        "duration": 310.0,
        "model": "Kim Vocal 2 (Ultra Fast)",
        "selected_audio_stream": 0,
        "status": "EXTRACTING",
        "message": "Stage 1/5: Extracting lossless audio stream...",
        "error_message": "",
        "started_at": "2026-11-05T01:14:00+00:00",
        "added_at": "2026-11-05T01:13:00+00:00",
        "output_media": ""
    }

    sec_cloud_en.queue_manager.state["jobs"] = {
        "job-en-1": job_en1,
        "job-en-2": job_en2,
        "job-en-3": job_en3,
        "job-en-4": job_en4
    }
    sec_cloud_en.refresh_list()
    QApplication.processEvents()

    wen2 = sec_cloud_en.job_widgets.get("job-en-2")
    if wen2:
        wen2.progress.setRange(0, 100)
        wen2.progress.setValue(58)
        wen2.lbl_eta.setVisible(True)
        wen2.lbl_eta.setText("Estimated Time: ~1m 40s")

    wen3 = sec_cloud_en.job_widgets.get("job-en-3")
    if wen3:
        wen3.progress.setRange(0, 100)
        wen3.progress.setValue(25)
        wen3.lbl_eta.setVisible(True)
        wen3.lbl_eta.setText("Uploading...")

    QApplication.processEvents()
    capture_widget(win, "cloud-journey-active-en.png")

    if wen1 := sec_cloud_en.job_widgets.get("job-en-1"):
        capture_widget(wen1, "job-card-completed-en.png")
    if wen2:
        capture_widget(wen2, "job-card-processing-en.png")

    # English Local Journey
    win.switch_view(1)
    sec_local_en = win.local_section

    job_len1 = {
        "id": "job-len-1",
        "original_media": r"C:\Media\Flora_World_Documentary.mp4",
        "mode": "Local (GPU)",
        "duration": 940.0,
        "model": "Band-Split RoFormer (HQ Vocal/Instrumental)",
        "selected_audio_stream": 0,
        "status": "PROCESSING_LOCAL",
        "message": "Processing audio locally... 68%",
        "error_message": "",
        "started_at": "2026-11-05T01:20:00+00:00",
        "added_at": "2026-11-05T01:19:00+00:00",
        "output_media": ""
    }

    job_len2 = {
        "id": "job-len-2",
        "original_media": r"C:\Media\Space_Exploration_Audio.wav",
        "mode": "Local (GPU)",
        "duration": 480.0,
        "model": "Kim Vocal 2 (Ultra Fast)",
        "selected_audio_stream": 0,
        "status": "COMPLETED",
        "message": "Purification Complete · Music removed successfully",
        "error_message": "",
        "started_at": "2026-11-05T01:15:00+00:00",
        "added_at": "2026-11-05T01:14:00+00:00",
        "final_elapsed_seconds": 64,
        "output_media": r"C:\Output\Space_Exploration_Audio_purified.wav"
    }

    sec_local_en.queue_manager.state["jobs"] = {"job-len-1": job_len1, "job-len-2": job_len2}
    sec_local_en.refresh_list()
    QApplication.processEvents()

    wlen1 = sec_local_en.job_widgets.get("job-len-1")
    if wlen1:
        wlen1.progress.setRange(0, 100)
        wlen1.progress.setValue(68)
        wlen1.lbl_eta.setVisible(True)
        wlen1.lbl_eta.setText("Time Remaining: ~2m 15s")

    QApplication.processEvents()
    capture_widget(win, "local-journey-active-en.png")

    # ══════════════════════════════════════════════════════
    # 5. OVERLAYS & MODEL BUTTONS (AR & EN)
    # ══════════════════════════════════════════════════════
    engine_size = "~2.7 GB" if DependencyManager.has_nvidia_gpu() else "~350 MB"

    # Arabic Local Engine Overlay
    win.apply_language("ar")
    win.switch_view(1)
    engine_overlay_ar = DownloadOverlayWidget(
        t("engine_title"), t("engine_desc", size=engine_size), t("engine_btn_download"), parent=win.centralWidget()
    )
    engine_overlay_ar.resize(win.centralWidget().size())
    engine_overlay_ar.show()
    QApplication.processEvents()
    capture_widget(win, "local-engine-overlay-ar.png")
    engine_overlay_ar.close()

    # English Local Engine Overlay
    win.apply_language("en")
    win.switch_view(1)
    engine_overlay_en = DownloadOverlayWidget(
        t("engine_title"), t("engine_desc", size=engine_size), t("engine_btn_download"), parent=win.centralWidget()
    )
    engine_overlay_en.resize(win.centralWidget().size())
    engine_overlay_en.show()
    QApplication.processEvents()
    capture_widget(win, "local-engine-overlay-en.png")
    engine_overlay_en.close()

    # Arabic Model Download Button
    win.apply_language("ar")
    win.switch_view(1)
    win.local_section.btn_add.setText("⬇ تنزيل RoFormer (~250 MB)")
    win.local_section.lbl_sub.setText("النموذج المختار: RoFormer · أعلى جودة")
    QApplication.processEvents()
    capture_widget(win, "local-download-button-ar.png")

    # English Model Download Button
    win.apply_language("en")
    win.switch_view(1)
    win.local_section.btn_add.setText("⬇ Download RoFormer (~250 MB)")
    win.local_section.lbl_sub.setText("Active Model: RoFormer · Highest Quality")
    QApplication.processEvents()
    capture_widget(win, "local-download-button-en.png")

    # Arabic FFmpeg Missing Overlay
    win.apply_language("ar")
    ffmpeg_overlay_ar = DownloadOverlayWidget(
        t("ffmpeg_title"), t("ffmpeg_desc"), t("ffmpeg_btn_download"), parent=win.centralWidget()
    )
    ffmpeg_overlay_ar.resize(win.centralWidget().size())
    ffmpeg_overlay_ar.show()
    QApplication.processEvents()
    capture_widget(win, "ffmpeg-missing-warning-ar.png")
    ffmpeg_overlay_ar.close()

    # English FFmpeg Missing Overlay
    win.apply_language("en")
    ffmpeg_overlay_en = DownloadOverlayWidget(
        t("ffmpeg_title"), t("ffmpeg_desc"), t("ffmpeg_btn_download"), parent=win.centralWidget()
    )
    ffmpeg_overlay_en.resize(win.centralWidget().size())
    ffmpeg_overlay_en.show()
    QApplication.processEvents()
    capture_widget(win, "ffmpeg-missing-warning-en.png")
    ffmpeg_overlay_en.close()

    # ══════════════════════════════════════════════════════
    # 6. DIALOGS (WITH "User" PATH)
    # ══════════════════════════════════════════════════════
    cfg_mock_ar = ConfigManager()
    cfg_mock_ar.set("kaggle_username", "mariam_researcher")
    cfg_mock_ar.set("kaggle_api_key", "KGAT_8a9f4c2e1b0d7e5a3c8f9b2d")
    cfg_mock_ar.set("output_folder", r"C:\Users\User\Videos\وثائقيات_منقاة")
    cfg_mock_ar.set("language", "ar")

    win.apply_language("ar")
    dlg_settings_ar = SettingsDialog(cfg_mock_ar, parent=win)
    dlg_settings_ar.show()
    QApplication.processEvents()
    capture_widget(dlg_settings_ar, "settings-dialog-ar.png")
    dlg_settings_ar.close()

    cfg_mock_en = ConfigManager()
    cfg_mock_en.set("kaggle_username", "mariam_researcher")
    cfg_mock_en.set("kaggle_api_key", "KGAT_8a9f4c2e1b0d7e5a3c8f9b2d")
    cfg_mock_en.set("output_folder", r"C:\Users\User\Videos\Purified_Audio")
    cfg_mock_en.set("language", "en")

    win.apply_language("en")
    dlg_settings_en = SettingsDialog(cfg_mock_en, parent=win)
    dlg_settings_en.show()
    QApplication.processEvents()
    capture_widget(dlg_settings_en, "settings-dialog-en.png")
    dlg_settings_en.close()

    # Audio Track Selector: Arabic
    win.apply_language("ar")
    mock_streams_ar = {
        r"C:\Media\وثائقي_حضارات_قديمة.mkv": [
            {
                "codec_name": "aac",
                "channels": 2,
                "tags": {"language": "ara", "title": "تعليق صوتي (عربي)"}
            },
            {
                "codec_name": "ac3",
                "channels": 6,
                "tags": {"language": "eng", "title": "مسار الصوت الأصلي (إنجليزي 5.1)"}
            }
        ]
    }
    dlg_track_ar = AudioTrackSelectDialog(mock_streams_ar, parent=win)
    dlg_track_ar.show()
    QApplication.processEvents()
    capture_widget(dlg_track_ar, "audio-track-selector.png")
    capture_widget(dlg_track_ar, "audio-track-selector-ar.png")
    dlg_track_ar.close()

    # Audio Track Selector: English
    win.apply_language("en")
    mock_streams_en = {
        r"C:\Media\Ancient_Civilizations.mkv": [
            {
                "codec_name": "aac",
                "channels": 2,
                "tags": {"language": "ara", "title": "Arabic Narration (Stereo)"}
            },
            {
                "codec_name": "ac3",
                "channels": 6,
                "tags": {"language": "eng", "title": "Original English Track (5.1 Surround)"}
            }
        ]
    }
    dlg_track_en = AudioTrackSelectDialog(mock_streams_en, parent=win)
    dlg_track_en.show()
    QApplication.processEvents()
    capture_widget(dlg_track_en, "audio-track-selector-en.png")
    dlg_track_en.close()

    # Delete Confirm: Arabic & English
    win.apply_language("ar")
    dlg_delete_ar = DeleteConfirmDialog(count=2, config=cfg_mock_ar, parent=win)
    dlg_delete_ar.show()
    QApplication.processEvents()
    capture_widget(dlg_delete_ar, "delete-confirm-dialog.png")
    capture_widget(dlg_delete_ar, "delete-confirm-dialog-ar.png")
    dlg_delete_ar.close()

    win.apply_language("en")
    dlg_delete_en = DeleteConfirmDialog(count=2, config=cfg_mock_en, parent=win)
    dlg_delete_en.show()
    QApplication.processEvents()
    capture_widget(dlg_delete_en, "delete-confirm-dialog-en.png")
    dlg_delete_en.close()

    # Phone Warning: Arabic & English
    win.apply_language("ar")
    dlg_phone_ar = PhoneVerificationWarningDialog(model_name="Band-Split RoFormer", parent=win)
    dlg_phone_ar.show()
    QApplication.processEvents()
    capture_widget(dlg_phone_ar, "phone-verification-warning-ar.png")
    dlg_phone_ar.close()

    win.apply_language("en")
    dlg_phone_en = PhoneVerificationWarningDialog(model_name="Band-Split RoFormer", parent=win)
    dlg_phone_en.show()
    QApplication.processEvents()
    capture_widget(dlg_phone_en, "phone-verification-warning-en.png")
    dlg_phone_en.close()

    win.close()
    print("\n✅ All screenshots generated cleanly in:")
    print(OUTPUT_DIR)
    sys.stdout.flush()
    os._exit(0)

if __name__ == "__main__":
    main()
