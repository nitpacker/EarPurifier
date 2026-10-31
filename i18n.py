"""
EarPurifier - Centralized Internationalization (i18n) Engine.
Provides comprehensive bilingual support (Arabic default, English fallback),
native RTL layout detection, and Arabic pluralization helpers.
"""

from typing import Dict, Optional
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

SUPPORTED_LANGUAGES: Dict[str, str] = {
    "ar": "العربية",
    "en": "English",
}

RTL_LANGUAGES = {"ar"}
DEFAULT_LANGUAGE = "ar"

_current_language = DEFAULT_LANGUAGE

# ─── Master Translation Dictionary (100% Parity Enforced) ─────────────────────
TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "ar": {
        # Window & Shell
        "app_title": "EarPurifier - استوديو عزل وتنقية الصوت بالذكاء الاصطناعي",
        "logo_tooltip": "EarPurifier - عزل وتنقية الصوت بالذكاء الاصطناعي",
        "engine_ready_tooltip": "محرك EarPurifier جاهز",

        # Sidebar Navigation
        "nav_cloud": "سحابي",
        "nav_cloud_tooltip": "معالجة سحابية (معالجات Kaggle مجانية)",
        "nav_local": "محلي",
        "nav_local_tooltip": "معالجة محلية (معالج الجهاز)",
        "nav_settings": "الإعدادات",
        "nav_settings_tooltip": "الإعدادات وبيانات الاعتماد",

        # Section Headers & Actions
        "cloud_engine_title": "المحرك السحابي (Kaggle T4)",
        "cloud_engine_sub": "معالجات سحابية مجانية · مزامنة سريعة للبيانات",
        "local_engine_title": "المحرك المحلي (معالج الجهاز)",
        "local_engine_sub_roformer": "أعلى دقة وجودة · ذكاء اصطناعي RoFormer",
        "local_engine_sub_mdx23c": "أداء متوازن وسريع · ذكاء اصطناعي MDX23C",
        "local_engine_sub_kim": "سرعة استنتاج قصوى · ذكاء اصطناعي Kim Vocal 2",
        "local_engine_sub_default": "معالجة محلية فائقة السرعة · ذكاء اصطناعي RoFormer",
        "btn_add_media": "＋ إضافة وسائط",
        "btn_download_model": "⬇ تنزيل النموذج ({size})",
        "btn_downloading_model": "⬇ جاري التنزيل...",
        "btn_select_mode": "تحديد",
        "btn_exit_selection": "إلغاء التحديد",
        "btn_clear_history": "مسح",
        "btn_open_output_folder": "📁 فتح مجلد الإخراج",
        "filter_label": "العرض:",
        "filter_all_jobs": "كافة المهام ({count})",
        "filter_in_progress": "قيد التنفيذ ({count})",
        "filter_completed": "المكتملة ({count})",
        "mariam_initiative": "🌱 من مبادرة مريم ↗",

        # Batch Action Bar
        "btn_select_all": "تحديد الكل",
        "btn_cancel": "إلغاء",
        "btn_remove_selected": "حذف المحدد",

        # Empty Queue Placeholder
        "empty_queue_title": "لا توجد مهام في قائمة الانتظار",
        "empty_queue_desc": "انقر على '＋ إضافة وسائط' أعلاه لرفع الملفات وعزل الصوت بالذكاء الاصطناعي.",

        # Group Headers
        "group_in_progress": "قيد التنفيذ",
        "group_completed": "المكتملة",

        # Job Card Widgets
        "badge_queued": "في الانتظار",
        "badge_running": "● قيد التنفيذ",
        "badge_completed": "✓ مكتمل",
        "badge_aborted": "■ تم الإلغاء",
        "badge_failed": "✕ فشل",
        "tag_mode_cloud": "سحابي",
        "tag_mode_local": "محلي",
        "btn_abort": "⏹ إلغاء",
        "btn_remove_tooltip": "إزالة من السجل",
        "btn_show_in_folder": "عرض في المجلد",
        "label_elapsed": "المنقضي:",
        "meta_saved_to_output": "تم الحفظ في المجلد",
        "time_m": "د",
        "time_s": "ث",
        "time_ms_format": "{mins} د {secs} ث",
        "time_s_format": "{secs} ث",
        "eta_in_queue": "في الانتظار",
        "eta_calculating": "الوقت المتبقي: جاري الحساب...",
        "eta_time_ms": "الوقت المتبقي: ~{mins} د {secs} ث",
        "eta_time_s": "الوقت المتبقي: ~{secs} ث",
        "eta_anytime": "الوقت المتبقي: وشيك الانتهاء...",

        # Job Status & Worker Messages
        "msg_purification_complete": "اكتملت التنقية · تم عزل الصوت بنجاح",
        "msg_job_aborted": "تم إلغاء المهمة",
        "msg_processing_failed": "فشلت عملية المعالجة",
        "msg_waiting_queue": "في انتظار بدء المعالجة...",
        "msg_isolating_vocals": "جاري عزل الصوت بالذكاء الاصطناعي...",
        "msg_aborted_by_user": "تم الإلغاء بواسطة المستخدم.",
        "msg_extracting_flac": "جاري استخراج صوت FLAC عالي الدقة...",
        "msg_pushing_kaggle": "جاري رفع الصوت إلى منصة Kaggle...",
        "msg_dispatching_kaggle": "جاري تشغيل معالج Kaggle السحابي...",
        "msg_waiting_kaggle_gpu": "في انتظار معالجة كرت الشاشة السحابي...",
        "msg_downloading_kaggle": "جاري تنزيل الصوت المنقى من Kaggle...",
        "msg_padding_remuxing": "جاري ضبط التوقيت ودمج وسائط الإخراج...",
        "msg_cleaned_temp": "تم تنظيف الملفات المؤقتة.",
        "msg_deleted_kaggle_dataset": "تم حذف مجموعة البيانات المؤقتة من Kaggle.",
        "msg_job_success": "اكتملت المهمة بنجاح!",
        "msg_job_aborted_cleaned": "تم إلغاء المهمة وتنظيف الملفات.",
        "msg_running_local_engine": "جاري تشغيل محرك الذكاء الاصطناعي المحلي...",
        "msg_processing_audio": "جاري معالجة الصوت...",
        "msg_processing_audio_pct": "جاري معالجة الصوت... {pct}٪",

        # Settings Dialog
        "settings_window_title": "الإعدادات - EarPurifier",
        "settings_header": "⚙  إعدادات التطبيق",
        "settings_grp_kaggle": "بيانات اعتماد Kaggle السحابية",
        "settings_kaggle_user": "اسم مستخدم Kaggle:",
        "settings_kaggle_user_ph": "اسم_المستخدم",
        "settings_kaggle_key": "مفتاح API الخاص بـ Kaggle:",
        "settings_grp_general": "الإعدادات العامة والمحرك",
        "settings_language": "لغة التطبيق:",
        "settings_out_folder": "مجلد الحفظ:",
        "settings_out_folder_ph": "اختر المجلد...",
        "settings_btn_browse": "استعراض",
        "settings_browse_title": "تحديد مجلد الإخراج",
        "settings_local_model": "نموذج الذكاء الاصطناعي المحلي:",
        "settings_enable_logging": "تفعيل تسجيل العمليات في الخلفية (موصى به)",
        "setting_check_updates": "التحقق من التحديثات تلقائياً (موصى به)",
        "btn_check_updates_now": "فحص الآن",
        "update_status_checking": "جاري التحقق من وجود تحديثات...",
        "update_status_latest": "أنت تستخدم أحدث إصدار ({version})",
        "update_status_available": "يوجد إصدار أحدث متاح: {version}",
        "update_status_error": "تعذر التحقق من التحديثات",
        "update_banner_title": "تحديث جديد متاح: {version}",
        "update_banner_desc": "يتوفر إصدار جديد من EarPurifier مع تحسينات وميزات جديدة.",
        "btn_download_update": "⬇ تنزيل التحديث",
        "btn_dismiss_update": "تذكيري لاحقاً",
        "btn_ignore_update": "تجاهل هذا الإصدار",
        "settings_btn_save": "حفظ الإعدادات",

        # Delete Confirmation Dialog
        "delete_dialog_title": "تأكيد الإزالة",
        "delete_confirm_desc": "سيؤدي هذا إلى إزالة العناصر المحددة من سجل جلستك.",
        "delete_output_files_chk": "حذف ملفات الإخراج المحلية الناتجة أيضاً",
        "delete_output_files_tip": "سيتم حذف الملفات الناتجة المنقاة فقط، ولن يتم المساس بالملفات الأصلية إطلاقاً.",
        "delete_output_files_note": "ملاحظة: لن يتم المساس بملفات الإدخال الأصلية بأي شكل.",
        "btn_remove": "إزالة",

        # Audio Track Selection Dialog
        "track_dialog_title": "اختيار المسار الصوتي - EarPurifier",
        "track_dialog_header": "🎵  تم اكتشاف عدة مسارات صوتية",
        "track_dialog_file": "الملف: {file_name}",
        "track_dialog_desc": "اختر المسار الصوتي الذي ترغب في عزله وتنقيته:",
        "track_item_format": "المسار {num}: {lang}{title} - {codec}، {channels} قنوات",
        "btn_select_track": "تأكيد الاختيار",

        # Overlays
        "ffmpeg_title": "أدوات FFmpeg و FFprobe غير مثبتة",
        "ffmpeg_desc": "تحقق التطبيق من مسارات النظام ومجلد البرامج ولم يعثر على هذه الأدوات الضرورية، وهي مطلوبة لاستخراج الصوت وإعادة بناء ملفات الوسائط.",
        "ffmpeg_btn_download": "تنزيل وتثبيت تلقائياً",
        "ffmpeg_status_failed": "فشل التنزيل: {message}",
        "engine_title": "محرك الذكاء الاصطناعي مطلوب",
        "engine_desc": "لمعالجة الصوت محلياً دون اتصال بالإنترنت على جهازك، يلزم تنزيل المحرك المحمول للذكاء الاصطناعي (~2.5 جيجابايت).",
        "engine_btn_download": "تنزيل وتثبيت المحرك تلقائياً",
        "engine_status_failed": "فشل التنزيل: {message}",

        # Alerts & Messages
        "alert_saved_title": "تم الحفظ",
        "alert_saved_msg": "تم حفظ الإعدادات بنجاح!",
        "close_active_job_title": "مهمة معالجة قيد التشغيل",
        "close_active_job_msg": "هناك مهمة معالجة صوتية نشطة حالياً. إغلاق EarPurifier الآن سيؤدي إلى إلغاء المهمة فوراً وإيقاف المعالجة على السحابة/الجهاز لحفظ الموارد.\n\nهل تريد الخروج وإلغاء المهمة؟",
        "btn_close_and_abort": "الخروج وإلغاء المهمة",
        "btn_keep_running": "متابعة المعالجة",
        "alert_no_selection_title": "لا يوجد تحديد",
        "alert_no_selection_msg": "يرجى تحديد مهمة واحدة على الأقل للحذف.",
        "alert_history_empty_title": "السجل فارغ",
        "alert_history_empty_msg": "لا توجد مهام مكتملة أو ملغاة أو فاشلة لمسحها.",
        "alert_missing_creds_title": "بيانات الاعتماد مفقودة",
        "alert_missing_creds_msg": "يرجى إدخال اسم مستخدم ومفتاح API حساب Kaggle في الإعدادات أولاً.",
        "alert_perm_denied_title": "تم رفض الوصول",
        "alert_perm_denied_msg": "تعذر إنشاء مجلد الإخراج. قد يمنع برنامج الحماية أو مضاد الفيروسات الوصول.\n\nالخطأ: {error}\n\nيرجى تغيير مجلد الإخراج من الإعدادات إلى سطح المكتب.",
        "file_dialog_title": "تحديد ملفات الوسائط",
        "filter_supported_media": "ملفات الوسائط المدعومة",
        "filter_video_files": "ملفات الفيديو",
        "filter_audio_files": "ملفات الصوت",
        "filter_all_files": "كافة الملفات",
        "alert_unsupported_title": "صيغة ملف غير مدعومة",
        "alert_unsupported_msg": "الملفات التالية ذات صيغ غير مدعومة وتم تخطيها:\n\n{files}\n\nالصيغ المدعومة:\n{supported}",
        "alert_analysis_err_title": "خطأ في فحص الملف",
        "alert_analysis_err_msg": "تعذر فحص مسارات '{filename}':\n{error}\n\nتم تخطي الملف.",
        "alert_no_audio_title": "لا توجد مسارات صوتية",
        "alert_no_audio_msg": "الملف المحدد لا يحتوي على أي مسار صوتي لتنقيته:\n\n{filename}",
        "alert_job_err_title": "خطأ في المعالجة",
        "alert_job_err_msg": "حدث خطأ أثناء معالجة المهمة:\n{error}",
        "alert_download_failed_title": "فشل التنزيل",
        "alert_download_failed_msg": "تعذر تنزيل نموذج الذكاء الاصطناعي:\n{message}",
        "unexpected_error_title": "خطأ غير متوقع - EarPurifier",
        "unexpected_error_msg": "حدث خطأ غير متوقع:\n\n{exc}\n\nيرجى مراجعة سجل التطبيق لمعرفة التفاصيل.",

        # Overhaul Studio Additions
        "theme_toggle_light": "التبديل إلى الوضع الفاتح",
        "theme_toggle_dark": "التبديل إلى الوضع الداكن",
        "btn_show_in_folder": "عرض في المجلد",
        "engine_telemetry_ready": "جاهز",
        "engine_telemetry_active": "نشط",
        "dropzone_title": "اسحب وأفلت ملفات الوسائط هنا",
        "dropzone_desc": "يدعم استيراد ملفات الفيديو والصوت لعزل الصوت البشري بدقة عالية",
        "dropzone_more_formats": "+ وغيرها الكثير!",
        "tab_all": "الكل",
        "tab_in_progress": "قيد التنفيذ",
        "tab_completed": "المكتملة",
        "track_active_badge": "محدد",
        "batch_dock_selected": "{count} محدد",
        "batch_dock_selected_zero": "لم يتم تحديد أي عنصر",
    },

    "en": {
        # Window & Shell
        "app_title": "EarPurifier - AI Audio Isolation Studio",
        "logo_tooltip": "EarPurifier - Serene AI Audio Isolation",
        "engine_ready_tooltip": "EarPurifier Engine Ready",

        # Sidebar Navigation
        "nav_cloud": "Cloud",
        "nav_cloud_tooltip": "Cloud Processing (Free Kaggle GPUs)",
        "nav_local": "Local",
        "nav_local_tooltip": "Local Processing (Hardware GPU)",
        "nav_settings": "Settings",
        "nav_settings_tooltip": "Settings & Credentials",

        # Section Headers & Actions
        "cloud_engine_title": "Cloud Engine (Kaggle T4)",
        "cloud_engine_sub": "Free Cloud GPUs · 30-Second Dataset Sync",
        "local_engine_title": "Local Engine (Hardware GPU)",
        "local_engine_sub_roformer": "Maximum Quality · RoFormer AI",
        "local_engine_sub_mdx23c": "Balanced Performance · MDX23C AI",
        "local_engine_sub_kim": "High-Speed Inference · Kim Vocal 2 AI",
        "local_engine_sub_default": "High-Speed Local Inference · RoFormer AI",
        "btn_add_media": "＋ Add Media",
        "btn_download_model": "⬇ Download Model ({size})",
        "btn_downloading_model": "⬇ Downloading...",
        "btn_select_mode": "Select",
        "btn_exit_selection": "Exit",
        "btn_clear_history": "Clear",
        "btn_open_output_folder": "📁 Open Output Folder",
        "filter_label": "View:",
        "filter_all_jobs": "All Jobs ({count})",
        "filter_in_progress": "In Progress ({count})",
        "filter_completed": "Completed ({count})",
        "mariam_initiative": "🌱 From Mariam Initiative ↗",

        # Batch Action Bar
        "btn_select_all": "Select All",
        "btn_cancel": "Cancel",
        "btn_remove_selected": "Remove Selected",

        # Empty Queue Placeholder
        "empty_queue_title": "No tasks in this queue",
        "empty_queue_desc": "Click '+ Add Media' above to upload media files and isolate vocals with AI.",

        # Group Headers
        "group_in_progress": "In Progress",
        "group_completed": "Completed",

        # Job Card Widgets
        "badge_queued": "QUEUED",
        "badge_running": "● RUNNING",
        "badge_completed": "✓ COMPLETED",
        "badge_aborted": "■ ABORTED",
        "badge_failed": "✕ FAILED",
        "tag_mode_cloud": "Cloud",
        "tag_mode_local": "Local",
        "btn_abort": "⏹ Abort",
        "btn_remove_tooltip": "Remove from history",
        "btn_show_in_folder": "Show in Folder",
        "label_elapsed": "Elapsed:",
        "meta_saved_to_output": "Saved to Output",
        "time_m": "m",
        "time_s": "s",
        "time_ms_format": "{mins}m {secs}s",
        "time_s_format": "{secs}s",
        "eta_in_queue": "In Queue",
        "eta_calculating": "ETA: Calculating...",
        "eta_time_ms": "ETA: ~{mins}m {secs}s",
        "eta_time_s": "ETA: ~{secs}s",
        "eta_anytime": "ETA: Anytime now...",

        # Job Status & Worker Messages
        "msg_purification_complete": "Purification complete · Audio isolated",
        "msg_job_aborted": "Job aborted",
        "msg_processing_failed": "Processing failed",
        "msg_waiting_queue": "Waiting in queue...",
        "msg_isolating_vocals": "Isolating vocals with AI...",
        "msg_aborted_by_user": "Aborted by user.",
        "msg_extracting_flac": "Extracting lossless FLAC...",
        "msg_pushing_kaggle": "Pushing audio to Kaggle dataset...",
        "msg_dispatching_kaggle": "Dispatching Kaggle worker kernel...",
        "msg_waiting_kaggle_gpu": "Waiting for Kaggle GPU processing...",
        "msg_downloading_kaggle": "Downloading clean audio from Kaggle...",
        "msg_padding_remuxing": "Padding/Trimming audio and Remuxing media...",
        "msg_cleaned_temp": "Cleaned up local temporary files.",
        "msg_deleted_kaggle_dataset": "Deleted temporary Kaggle dataset.",
        "msg_job_success": "Job finished successfully!",
        "msg_job_aborted_cleaned": "Job aborted and cleaned up.",
        "msg_running_local_engine": "Running Local AI Engine...",
        "msg_processing_audio": "Processing audio...",
        "msg_processing_audio_pct": "Processing audio... {pct}%",

        # Settings Dialog
        "settings_window_title": "Settings - EarPurifier",
        "settings_header": "⚙  Application Settings",
        "settings_grp_kaggle": "Kaggle Cloud Credentials",
        "settings_kaggle_user": "Kaggle Username:",
        "settings_kaggle_user_ph": "your_kaggle_username",
        "settings_kaggle_key": "Kaggle API Key:",
        "settings_grp_general": "General & Engine Settings",
        "settings_language": "Language:",
        "settings_out_folder": "Output Folder:",
        "settings_out_folder_ph": "Select folder...",
        "settings_btn_browse": "Browse",
        "settings_browse_title": "Select Output Folder",
        "settings_local_model": "Local AI Model:",
        "settings_enable_logging": "Enable Background Logging (Recommended)",
        "setting_check_updates": "Check for updates automatically (Recommended)",
        "btn_check_updates_now": "Check Now",
        "update_status_checking": "Checking for updates...",
        "update_status_latest": "You are on the latest version ({version})",
        "update_status_available": "A new version is available: {version}",
        "update_status_error": "Could not check for updates",
        "update_banner_title": "New Version Available: {version}",
        "update_banner_desc": "A new release of EarPurifier is available with improvements and new features.",
        "btn_download_update": "⬇ Download Update",
        "btn_dismiss_update": "Remind Me Later",
        "btn_ignore_update": "Skip This Version",
        "settings_btn_save": "Save Settings",

        # Delete Confirmation Dialog
        "delete_dialog_title": "Confirm Removal",
        "delete_confirm_desc": "This will remove the selected entry from your session history.",
        "delete_output_files_chk": "Delete local output file(s) too",
        "delete_output_files_tip": "Will only delete generated/purified output files, never original inputs.",
        "delete_output_files_note": "Note: Original input files will never be touched.",
        "btn_remove": "Remove",

        # Audio Track Selection Dialog
        "track_dialog_title": "Select Audio Track - EarPurifier",
        "track_dialog_header": "🎵  Multiple Audio Tracks Detected",
        "track_dialog_file": "File: {file_name}",
        "track_dialog_desc": "Select which audio track to isolate and purify:",
        "track_item_format": "Track {num}: {lang}{title} - {codec}, {channels} channels",
        "btn_select_track": "Select Track",

        # Overlays
        "ffmpeg_title": "FFmpeg & FFprobe Not Installed",
        "ffmpeg_desc": "EarPurifier checked your System PATH and AppData bin folder but could not find these required tools. They are needed to extract and rebuild media files.",
        "ffmpeg_btn_download": "Download Automatically",
        "ffmpeg_status_failed": "Failed: {message}",
        "engine_title": "Engine Required",
        "engine_desc": "To process audio completely offline on your own hardware, EarPurifier needs to download a portable AI engine (~2.5GB).",
        "engine_btn_download": "Download & Install Automatically",
        "engine_status_failed": "Failed: {message}",

        # Alerts & Messages
        "alert_saved_title": "Saved",
        "alert_saved_msg": "Settings saved successfully!",
        "close_active_job_title": "Processing in Progress",
        "close_active_job_msg": "An audio separation job is currently active. Closing EarPurifier now will immediately abort the job and cancel cloud/local processing to conserve resources.\n\nAre you sure you want to exit and abort?",
        "btn_close_and_abort": "Exit & Abort",
        "btn_keep_running": "Keep Running",
        "alert_no_selection_title": "No Selection",
        "alert_no_selection_msg": "Please select at least one job to delete.",
        "alert_history_empty_title": "History Empty",
        "alert_history_empty_msg": "No completed, failed, or aborted jobs to clear.",
        "alert_missing_creds_title": "Missing Credentials",
        "alert_missing_creds_msg": "Please set your Kaggle Username and API Key in Settings first.",
        "alert_perm_denied_title": "Permission Denied",
        "alert_perm_denied_msg": "Could not create output folder. Windows Defender or an antivirus might be blocking access.\n\nError: {error}\n\nPlease change the output folder in Settings to your Desktop.",
        "file_dialog_title": "Select Media Files",
        "filter_supported_media": "Supported Media Files",
        "filter_video_files": "Video Files",
        "filter_audio_files": "Audio Files",
        "filter_all_files": "All Files",
        "alert_unsupported_title": "Unsupported File Format",
        "alert_unsupported_msg": "The following file(s) have unsupported extensions and were skipped:\n\n{files}\n\nSupported formats:\n{supported}",
        "alert_analysis_err_title": "Analysis Error",
        "alert_analysis_err_msg": "Could not inspect streams for '{filename}':\n{error}\n\nSkipping file.",
        "alert_no_audio_title": "No Audio Streams",
        "alert_no_audio_msg": "The selected file contains no audio streams to purify:\n\n{filename}",
        "alert_job_err_title": "Job Error",
        "alert_job_err_msg": "An error occurred in job:\n{error}",
        "alert_download_failed_title": "Download Failed",
        "alert_download_failed_msg": "Failed to download AI model:\n{message}",
        "unexpected_error_title": "Unexpected Error - EarPurifier",
        "unexpected_error_msg": "An unexpected error occurred:\n\n{exc}\n\nPlease check the application log for details.",

        # Overhaul Studio Additions
        "theme_toggle_light": "Switch to Light Mode",
        "theme_toggle_dark": "Switch to Dark Mode",
        "btn_show_in_folder": "Show in Folder",
        "engine_telemetry_ready": "READY",
        "engine_telemetry_active": "ACTIVE",
        "dropzone_title": "Drag and Drop Media Files Here",
        "dropzone_desc": "Import audio or video files to isolate clear vocal stems with AI precision",
        "dropzone_more_formats": "+ and much more!",
        "tab_all": "All",
        "tab_in_progress": "In Progress",
        "tab_completed": "Completed",
        "track_active_badge": "Active",
        "batch_dock_selected": "{count} selected",
        "batch_dock_selected_zero": "0 items selected",
    }
}

# ─── Worker Message Exact Match Map ───────────────────────────────────────────
WORKER_MESSAGE_KEY_MAP = {
    "Purification complete · Audio isolated": "msg_purification_complete",
    "Job aborted": "msg_job_aborted",
    "Processing failed": "msg_processing_failed",
    "Waiting in queue...": "msg_waiting_queue",
    "Isolating vocals with AI...": "msg_isolating_vocals",
    "Aborted by user.": "msg_aborted_by_user",
    "Extracting lossless FLAC...": "msg_extracting_flac",
    "Pushing audio to Kaggle dataset...": "msg_pushing_kaggle",
    "Dispatching Kaggle worker kernel...": "msg_dispatching_kaggle",
    "Waiting for Kaggle GPU processing...": "msg_waiting_kaggle_gpu",
    "Downloading clean audio from Kaggle...": "msg_downloading_kaggle",
    "Padding/Trimming audio and Remuxing media...": "msg_padding_remuxing",
    "Cleaned up local temporary files.": "msg_cleaned_temp",
    "Deleted temporary Kaggle dataset.": "msg_deleted_kaggle_dataset",
    "Job finished successfully!": "msg_job_success",
    "Job aborted and cleaned up.": "msg_job_aborted_cleaned",
    "Running Local AI Engine...": "msg_running_local_engine",
    "Processing audio...": "msg_processing_audio",
}


# ─── Core Translation Accessors ───────────────────────────────────────────────
def get_current_language() -> str:
    """Returns the currently active language code ('ar' or 'en')."""
    global _current_language
    return _current_language


def set_language(lang: str) -> None:
    """Sets the active language code."""
    global _current_language
    if lang in SUPPORTED_LANGUAGES:
        _current_language = lang


def is_rtl(lang: Optional[str] = None) -> bool:
    """Returns True if the specified (or active) language is Right-to-Left."""
    target_lang = lang if lang is not None else get_current_language()
    return target_lang in RTL_LANGUAGES


def apply_app_direction(app: Optional[QApplication] = None, lang: Optional[str] = None) -> None:
    """Sets Qt's global application layout direction according to language."""
    target_app = app or QApplication.instance()
    if target_app:
        target_app.setLayoutDirection(Qt.RightToLeft if is_rtl(lang) else Qt.LeftToRight)


def t(key: str, **kwargs) -> str:
    """
    Fetches the translated string for `key`.
    Falls back to English if key is missing in active language,
    or returns `key` itself if missing in both.
    Supports python format interpolation safely.
    """
    lang = get_current_language()
    val = TRANSLATIONS.get(lang, {}).get(key)
    if val is None:
        val = TRANSLATIONS.get("en", {}).get(key, key)
    if kwargs:
        try:
            return val.format(**kwargs)
        except Exception:
            return val
    return val


# ─── Arabic Pluralization & Formatting Helpers ────────────────────────────────
def format_jobs_count(count: int, lang: Optional[str] = None) -> str:
    """
    Returns grammatically correct string for selected job counts.
    Arabic plural rules:
    - 0: لم يتم تحديد أي مهمة
    - 1: تم تحديد مهمة واحدة
    - 2: تم تحديد مهمتين
    - 3..10: تم تحديد {count} مهام
    - 11+: تم تحديد {count} مهمة
    """
    active_lang = lang or get_current_language()
    if active_lang == "ar":
        if count == 0:
            return "لم يتم تحديد أي مهمة"
        elif count == 1:
            return "تم تحديد مهمة واحدة"
        elif count == 2:
            return "تم تحديد مهمتين"
        elif 3 <= count <= 10:
            return f"تم تحديد {count} مهام"
        else:
            return f"تم تحديد {count} مهمة"
    else:
        if count == 1:
            return "1 job selected"
        else:
            return f"{count} jobs selected"


def format_delete_confirm_msg(count: int, lang: Optional[str] = None) -> str:
    """
    Returns grammatically correct title message for job deletion prompt.
    """
    active_lang = lang or get_current_language()
    if active_lang == "ar":
        if count == 1:
            return "هل تريد إزالة هذه المهمة من السجل؟"
        elif count == 2:
            return "هل تريد إزالة مهمتين من السجل؟"
        elif 3 <= count <= 10:
            return f"هل تريد إزالة {count} مهام من السجل؟"
        else:
            return f"هل تريد إزالة {count} مهمة من السجل؟"
    else:
        if count == 1:
            return "Remove this job from history?"
        else:
            return f"Remove {count} jobs from history?"


def translate_worker_message(msg: str) -> str:
    """
    Translates known background worker logs and status updates for the UI
    while preserving clean, localized descriptive messages in Arabic and English.
    """
    if not msg:
        return ""

    # Exact dictionary match
    if msg in WORKER_MESSAGE_KEY_MAP:
        return t(WORKER_MESSAGE_KEY_MAP[msg])

    # Dynamic percentage message: "Processing audio... 45%"
    if msg.startswith("Processing audio...") and "%" in msg:
        pct_part = msg.replace("Processing audio...", "").replace("%", "").strip()
        if pct_part.isdigit():
            return t("msg_processing_audio_pct", pct=pct_part)

    # Kaggle background kernel polling messages
    msg_lower = msg.lower()
    if "polling" in msg_lower or "kaggle status" in msg_lower:
        if "queued" in msg_lower:
            return t("msg_waiting_kaggle_gpu")
        elif "complete" in msg_lower:
            return t("msg_downloading_kaggle")
        else:
            return t("msg_isolating_vocals")

    # Local model initialization & audio processing
    if msg.startswith("Model ") and "Processing audio" in msg:
        return t("msg_processing_audio")

    # Cancellation / Cleanup in progress
    if "aborting:" in msg_lower or "cancelling kaggle kernel" in msg_lower:
        return t("msg_job_aborted")

    # Network retries
    if "interrupted" in msg_lower and "retrying" in msg_lower:
        return t("msg_waiting_kaggle_gpu")

    # Return original message if no match found
    return msg
