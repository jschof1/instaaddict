import os
import re
import json
import shutil
import time
import logging
import subprocess
import struct
import yaml
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta

from InstaAddict.core.plugin_loader import Plugin
from InstaAddict.core.utils import random_sleep
from InstaAddict.core.gemini_vision import get_vision_caption
from InstaAddict.core.resources import ResourceID

logger = logging.getLogger(__name__)

# Constants
ALLOWED_EXTENSIONS: tuple = (".jpg", ".jpeg", ".png", ".mp4")
DEFAULT_RATE_LIMIT_HOURS: float = 12.0
PUBLICATION_HISTORY_FILENAME: str = ".upload_history.json"


def _parse_mp4_dimensions(media_path: str) -> Optional[Tuple[int, int]]:
    """Extracts (width, height) of primary video track from an MP4 file by parsing ISO BMFF atoms.

    Parses 'moov' -> 'trak' -> 'tkhd' box without any external binary dependencies.
    """
    if not media_path or not os.path.exists(media_path):
        return None
    try:
        file_size = os.path.getsize(media_path)
        with open(media_path, "rb") as f:
            offset = 0
            while offset < file_size:
                f.seek(offset)
                hdr = f.read(8)
                if len(hdr) < 8:
                    break
                box_size, box_type = struct.unpack(">I4s", hdr)
                if box_size == 1:
                    hdr64 = f.read(8)
                    if len(hdr64) < 8:
                        break
                    box_size = struct.unpack(">Q", hdr64)[0]
                    hdr_len = 16
                elif box_size == 0:
                    box_size = file_size - offset
                    hdr_len = 8
                else:
                    hdr_len = 8

                if box_size < hdr_len:
                    break

                if box_type == b"moov":
                    moov_content_len = min(box_size - hdr_len, 10 * 1024 * 1024)
                    moov_bytes = f.read(moov_content_len)
                    trak_idx = 0
                    while True:
                        trak_idx = moov_bytes.find(b"trak", trak_idx)
                        if trak_idx == -1:
                            break
                        if trak_idx >= 4:
                            trak_size = struct.unpack(">I", moov_bytes[trak_idx - 4 : trak_idx])[0]
                            trak_bytes = moov_bytes[trak_idx - 4 : trak_idx - 4 + trak_size]
                            tkhd_idx = trak_bytes.find(b"tkhd")
                            if tkhd_idx != -1 and tkhd_idx + 8 <= len(trak_bytes):
                                ver = trak_bytes[tkhd_idx + 4]
                                skip = 32 if ver == 1 else 20
                                dim_offset = tkhd_idx + 4 + 4 + skip + 52
                                if dim_offset + 8 <= len(trak_bytes):
                                    w_raw = struct.unpack(">I", trak_bytes[dim_offset : dim_offset + 4])[0] >> 16
                                    h_raw = struct.unpack(">I", trak_bytes[dim_offset + 4 : dim_offset + 8])[0] >> 16
                                    if w_raw > 0 and h_raw > 0:
                                        return int(w_raw), int(h_raw)
                        trak_idx += 4
                    break
                offset += box_size
    except Exception as e:
        logger.debug(f"_parse_mp4_dimensions error for {media_path}: {e}")
    return None


def _record_publication(published_dir: str, filename: str, caption: str = "") -> None:
    """Appends successful publication record to durable history ledger (AUDIT-133-G05)."""
    if not published_dir:
        return
    os.makedirs(published_dir, exist_ok=True)
    ledger_path = os.path.join(published_dir, PUBLICATION_HISTORY_FILENAME)
    entry = {
        "filename": filename,
        "published_at": datetime.now().isoformat(),
        "timestamp": time.time(),
        "caption": caption[:100] if caption else "",
    }
    history: List[Dict[str, Any]] = []
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, list):
                    history = loaded
        except Exception as e:
            logger.debug(f"Failed to read existing upload history ledger: {e}")
            history = []
    history.append(entry)
    try:
        with open(ledger_path, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        logger.debug(f"Failed to write upload history ledger: {e}")


class UploadPostsPlugin(Plugin):
    """Uploads curated content from local queue to Instagram feed."""

    def __init__(self) -> None:
        super().__init__()
        self.description: str = (
            "Uploads curated content from local queue to Instagram feed"
        )
        self.arguments: List[Dict[str, Any]] = [
            {
                "arg": "--upload-posts",
                "help": "Upload curated posts from accounts/<username>/content_queue/pending",
                "action": "store_true",
                "operation": True,
            },
            {
                "arg": "--upload-rate-limit-hours",
                "metavar": "12.0",
                "type": float,
                "default": None,
                "help": "Rate limit between uploads in hours (default: 12.0 in config or fallback, 0 to disable)",
            },
            {
                "arg": "--upload-queue-dir",
                "metavar": "path/to/queue",
                "default": None,
                "help": "Custom path to the upload media queue directory",
            },
            {
                "arg": "--upload-hashtags-in-comment",
                "help": "Post hashtags in first comment instead of main caption",
                "action": "store_true",
            },
            {
                "arg": "--only-upload",
                "help": "Execute only the upload post job and exit immediately (on-demand upload mode)",
                "action": "store_true",
            },
            {
                "arg": "--upload-now",
                "help": "Alias for --only-upload",
                "action": "store_true",
            },
            {
                "arg": "--upload-force",
                "help": "Force upload immediately by bypassing the 12-hour rate-limit check",
                "action": "store_true",
            },
            {
                "arg": "--upload-force-square",
                "help": "Force 1:1 square crop even if source media is landscape or portrait",
                "action": "store_true",
            },
        ]

    def _resolve_username(self, configs: Any, sessions: Any) -> str:
        """Safely resolves the Instagram username across CLI args, sessions, and config path."""
        # Priority 1: CLI args
        if hasattr(configs, "args") and hasattr(configs.args, "username"):
            cli_user = configs.args.username
            if cli_user and str(cli_user).strip():
                return str(cli_user).strip()

        # Priority 2: Active session
        if sessions and len(sessions) > 0:
            session = sessions[-1]
            session_user = getattr(session, "my_username", None)
            if session_user and str(session_user).strip():
                return str(session_user).strip()

        # Priority 3: Config file path parsing
        config_path = ""
        if hasattr(configs, "args") and hasattr(configs.args, "config"):
            config_path = str(configs.args.config)

        if config_path:
            # Accept both separators on every OS (a Windows-style path read on Linux, and vice versa)
            norm_path = os.path.normpath(config_path.replace("\\", "/"))
            parts = re.split(r"[\\/]", norm_path)
            if "accounts" in parts:
                idx = parts.index("accounts")
                if idx + 1 < len(parts):
                    cand = parts[idx + 1]
                    if cand and not cand.endswith((".yml", ".yaml")):
                        return cand

        # Priority 4: Look in accounts/ directory if exactly one account exists
        accounts_dir = "accounts"
        if os.path.exists(accounts_dir) and os.path.isdir(accounts_dir):
            subdirs = [
                d
                for d in os.listdir(accounts_dir)
                if os.path.isdir(os.path.join(accounts_dir, d))
                and not d.startswith(".")
            ]
            if len(subdirs) == 1:
                return subdirs[0]

        return ""

    def _get_rate_limit_hours(self, configs: Any, config_path: str) -> float:
        """Resolves effective rate limit in hours from CLI args, YAML config, or default."""
        if hasattr(configs, "args"):
            if getattr(configs.args, "upload_force", False) is True:
                logger.info("Upload rate limit bypassed via --upload-force.")
                return 0.0
            cli_hours = getattr(configs.args, "upload_rate_limit_hours", None)
            if cli_hours is not None:
                try:
                    return float(cli_hours)
                except (ValueError, TypeError):
                    pass

        if config_path and os.path.exists(config_path):
            try:
                import yaml

                with open(config_path, "r", encoding="utf-8") as f:
                    user_conf = yaml.safe_load(f) or {}
                    if "upload-rate-limit-hours" in user_conf:
                        return float(user_conf["upload-rate-limit-hours"])
            except Exception as e:
                logger.debug(
                    f"Failed to read upload-rate-limit-hours from {config_path}: {e}"
                )

        return DEFAULT_RATE_LIMIT_HOURS

    def _is_rate_limited(self, published_dir: str, rate_limit_hours: float) -> bool:
        """Enforces a global rate limit based on persistent history ledger and file mtimes."""
        if rate_limit_hours <= 0:
            logger.info("Upload rate limit is disabled (<= 0 hours specified).")
            return False

        if not os.path.exists(published_dir):
            return False

        limit_threshold: datetime = datetime.now() - timedelta(
            hours=rate_limit_hours
        )
        latest_mtime: Optional[datetime] = None

        # Tier 1: Check persistent history ledger (AUDIT-133-G05)
        ledger_path = os.path.join(published_dir, PUBLICATION_HISTORY_FILENAME)
        if os.path.exists(ledger_path):
            try:
                with open(ledger_path, "r", encoding="utf-8") as f:
                    history = json.load(f)
                    if isinstance(history, list):
                        for item in history:
                            ts = item.get("timestamp")
                            pub_at = item.get("published_at")
                            dt = None
                            if ts:
                                try:
                                    dt = datetime.fromtimestamp(float(ts))
                                except Exception:
                                    dt = None
                            elif pub_at:
                                try:
                                    dt = datetime.fromisoformat(str(pub_at))
                                except Exception:
                                    dt = None
                            if dt and (latest_mtime is None or dt > latest_mtime):
                                latest_mtime = dt
            except Exception as e:
                logger.debug(f"Failed to parse upload history ledger: {e}")

        # Tier 2: Check filesystem mtime (fallback or whichever is newer)
        for root, _, files in os.walk(published_dir):
            for file in files:
                if file.lower().endswith(ALLOWED_EXTENSIONS):
                    file_path: str = os.path.join(root, file)
                    try:
                        mtime: datetime = datetime.fromtimestamp(
                            os.path.getmtime(file_path)
                        )
                        if latest_mtime is None or mtime > latest_mtime:
                            latest_mtime = mtime
                    except OSError as e:
                        logger.debug(
                            f"Failed to read file timestamp for rate limit check: {e}"
                        )

        if latest_mtime and latest_mtime > limit_threshold:
            elapsed_hours = (
                datetime.now() - latest_mtime
            ).total_seconds() / 3600.0
            remaining_hours = max(0.0, rate_limit_hours - elapsed_hours)
            logger.info(
                f"Upload rate limit active. Last upload was {elapsed_hours:.1f}h ago. "
                f"Need to wait {remaining_hours:.1f}h more before next post (limit: {rate_limit_hours}h)."
            )
            return True

        return False

    def _enrich_hashtags_if_needed(
        self, caption: str, username: str, max_retries: int = 5
    ) -> str:
        """Enriches caption with rotating hashtags from HashtagManager, retrying up to 5 times."""
        if not username:
            return caption
        existing_tags = re.findall(r"#([a-zA-Z0-9_]+)", caption)
        if len(existing_tags) >= 3:
            return caption

        tags_to_add = []
        for attempt in range(max_retries):
            try:
                from InstaAddict.core.hashtag_manager import HashtagManager

                manager = HashtagManager.get_instance(username)
                candidates = manager.get_post_hashtags(count=5)
                lower_existing = {t.lower() for t in existing_tags}
                for tag in candidates:
                    clean_tag = tag.strip().lstrip("#")
                    if clean_tag and clean_tag.lower() not in lower_existing:
                        tags_to_add.append(f"#{clean_tag}")
                        if len(existing_tags) + len(tags_to_add) >= 5:
                            break
                if tags_to_add:
                    break
            except Exception as e:
                logger.debug(
                    f"HashtagManager enrichment error (attempt {attempt + 1}/{max_retries}): {e}"
                )
                if attempt < max_retries - 1:
                    time.sleep(1)

        # Fallback if HashtagManager yielded no tags (CO-025 / F-08 — configurable via YAML)
        if not tags_to_add:
            fallback_tags_from_config: List[str] = []
            if hasattr(self, "_config_path_cache"):
                _cfg_path = getattr(self, "_config_path_cache", "")
                if _cfg_path and os.path.exists(_cfg_path):
                    try:
                        with open(_cfg_path, "r", encoding="utf-8") as _cf:
                            _user_conf = yaml.safe_load(_cf) or {}
                            _raw_tags = _user_conf.get("upload-fallback-hashtags", [])
                            if isinstance(_raw_tags, list):
                                fallback_tags_from_config = [
                                    f"#{t.strip().lstrip('#')}" for t in _raw_tags if isinstance(t, str) and t.strip()
                                ]
                    except Exception as _cfg_err:
                        logger.debug(f"Could not read upload-fallback-hashtags from config: {_cfg_err}")

            fallback_tags = fallback_tags_from_config or [
                "#photooftheday",
                "#instagood",
                "#dailylife",
                "#lifestyle",
                "#moments",
            ]
            lower_existing = {t.lower() for t in existing_tags}
            for tag in fallback_tags:
                clean_tag = tag.strip().lstrip("#")
                if clean_tag.lower() not in lower_existing:
                    tags_to_add.append(f"#{clean_tag}")
                    if len(existing_tags) + len(tags_to_add) >= 5:
                        break

        if tags_to_add:
            tag_block = " ".join(tags_to_add)
            if caption:
                caption = f"{caption.rstrip()}\n\n{tag_block}"
            else:
                caption = tag_block
            logger.info(
                f"Enriched post caption with {len(tags_to_add)} hashtags: {tag_block}"
            )

        return caption

    def _extract_caption(
        self, pending_dir: str, media_file: str, config_path: str, username: str = ""
    ) -> str:
        """Extracts caption from .txt sidecar (extended by AI), .json sidecar, or Gemini Vision AI."""
        base_name = os.path.splitext(media_file)[0]
        media_path = os.path.join(pending_dir, media_file)

        # 1. Text file sidecar (.txt) - Contextual guidance for AI captioner
        txt_path = os.path.join(pending_dir, f"{base_name}.txt")
        txt_guidance = ""
        if os.path.exists(txt_path):
            try:
                with open(txt_path, "r", encoding="utf-8-sig") as f:
                    txt_guidance = f.read().strip()
            except Exception as e:
                logger.warning(
                    f"Failed reading text caption override {txt_path}: {e}"
                )

        # 2. JSON file sidecar (.json) - Explicit static caption override if no .txt guidance
        if not txt_guidance:
            json_path = os.path.join(pending_dir, f"{base_name}.json")
            if os.path.exists(json_path):
                try:
                    with open(json_path, "r", encoding="utf-8-sig") as f:
                        data = json.load(f)
                        caption = data.get("caption", "").strip()
                        if caption:
                            logger.info(
                                f"Human JSON caption override found for {media_file} ({json_path})."
                            )
                            return self._enrich_hashtags_if_needed(
                                caption, username
                            )
                except Exception as e:
                    logger.warning(
                        f"Failed reading JSON caption override {json_path}: {e}"
                    )

        # 3. Check if txt_guidance is already a complete elaborated caption with hashtags
        existing_tags = re.findall(r"#([a-zA-Z0-9_]+)", txt_guidance)
        if txt_guidance and len(existing_tags) >= 3 and len(txt_guidance) >= 50:
            logger.info(
                f"Existing caption in {txt_path} is already fully elaborated with {len(existing_tags)} hashtags."
            )
            return self._enrich_hashtags_if_needed(txt_guidance, username)

        # 4. Mandatory Elaboration: Engage Gemini Vision AI to visually analyze and elaborate post
        persona = "casual Instagram user"
        if config_path and os.path.exists(config_path):
            try:
                import yaml

                with open(config_path, "r", encoding="utf-8") as yc:
                    user_conf = yaml.safe_load(yc) or {}
                    persona = user_conf.get("ai-persona", persona)
            except Exception:
                pass

        if txt_guidance:
            logger.info(
                f"Contextual guidance found for {media_file} ({txt_path}): {txt_guidance!r}. "
                "Engaging Gemini Vision AI to elaborate caption..."
            )
        else:
            logger.info(
                f"No caption sidecar found for {media_file}. Engaging Gemini Vision AI to generate caption..."
            )

        caption = ""
        try:
            caption = get_vision_caption(
                media_path, persona, user_context=txt_guidance
            )
        except Exception as e:
            logger.error(
                f"Gemini Vision AI caption generation failed for {media_file}: {e}"
            )

        # Fallback if Vision AI returned empty: use raw note or fallback
        if not caption:
            if txt_guidance:
                logger.info(
                    f"Vision AI produced no output. Falling back to raw contextual note for {media_file}."
                )
                caption = txt_guidance
            else:
                caption = f"Photo from {base_name}"

        # 5. Mandatory Hashtags: Enforce proper hashtags on the elaborated caption
        final_caption = self._enrich_hashtags_if_needed(
            caption.strip(), username
        )

        # 6. Persist elaborated caption back to sidecar so disk record is synchronized
        try:
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(final_caption)
            logger.info(
                f"Persisted mandatory elaborated caption & hashtags to {txt_path}"
            )
        except Exception as e:
            logger.debug(
                f"Failed to persist elaborated caption to {txt_path}: {e}"
            )

        return final_caption

    def run(
        self,
        device: Any,
        configs: Any,
        storage: Any,
        sessions: Any,
        profile_filter: Any,
        plugin: Any,
    ) -> None:
        """Main plugin execution hook."""
        username = self._resolve_username(configs, sessions)
        if not username:
            logger.error(
                "UploadPostsPlugin: Unable to resolve account username. Cannot locate content queue."
            )
            return

        config_path: str = ""
        if hasattr(configs, "args") and hasattr(configs.args, "config"):
            config_path = str(configs.args.config)
        # Cache config path for use in _enrich_hashtags_if_needed (CO-025)
        self._config_path_cache = config_path

        # Flag: post hashtags in first comment instead of caption (CO-020 / F-02)
        hashtags_in_comment = getattr(configs.args, "upload_hashtags_in_comment", False) is True

        # Flag: force 1:1 square crop even if source media is landscape or portrait
        force_square = (
            getattr(configs.args, "upload_force_square", False) is True
            if hasattr(configs, "args")
            else False
        )
        if not force_square and config_path and os.path.exists(config_path):
            try:
                import yaml

                with open(config_path, "r", encoding="utf-8") as f:
                    user_conf = yaml.safe_load(f) or {}
                    if user_conf.get("upload-force-square", False) is True:
                        force_square = True
            except Exception:
                pass

        # Check for custom queue directory via CLI args or YAML config
        custom_queue_dir = None
        if hasattr(configs, "args") and hasattr(configs.args, "upload_queue_dir"):
            raw_dir = configs.args.upload_queue_dir
            if isinstance(raw_dir, str) and raw_dir.strip():
                custom_queue_dir = raw_dir.strip()

        if not custom_queue_dir and config_path and os.path.exists(config_path):
            try:
                import yaml

                with open(config_path, "r", encoding="utf-8") as f:
                    user_conf = yaml.safe_load(f) or {}
                    raw_dir = user_conf.get("upload-queue-dir")
                    if isinstance(raw_dir, str) and raw_dir.strip():
                        custom_queue_dir = raw_dir.strip()
            except Exception:
                pass

        if custom_queue_dir:
            custom_queue_dir = str(custom_queue_dir).strip()
            if os.path.exists(os.path.join(custom_queue_dir, "pending")):
                pending_dir = os.path.join(custom_queue_dir, "pending")
                published_dir = os.path.join(custom_queue_dir, "published")
            elif os.path.exists(custom_queue_dir):
                pending_dir = custom_queue_dir
                published_dir = os.path.join(os.path.dirname(custom_queue_dir), "published")
            else:
                pending_dir = custom_queue_dir
                published_dir = os.path.join(os.path.dirname(custom_queue_dir), "published")
        else:
            # Support standard content_queue and legacy upload_queue
            pending_candidates = [
                os.path.join("accounts", username, "content_queue", "pending"),
                os.path.join("accounts", username, "upload_queue", "pending"),
            ]
            pending_dir = None
            for cand in pending_candidates:
                if os.path.exists(cand):
                    pending_dir = cand
                    break

            if not pending_dir:
                pending_dir = pending_candidates[0]
                logger.info(
                    f"UploadPostsPlugin: Pending queue directory does not exist: {pending_dir}. Skipping upload."
                )
                return

            published_dir = os.path.join(os.path.dirname(pending_dir), "published")

        rate_limit_hours = self._get_rate_limit_hours(configs, config_path)
        if self._is_rate_limited(published_dir, rate_limit_hours):
            return

        # Case-insensitive media discovery, ignoring active temp files and hidden files (AUDIT-133-G04)
        all_files = sorted(os.listdir(pending_dir))
        media_files = [
            f
            for f in all_files
            if f.lower().endswith(ALLOWED_EXTENSIONS)
            and not f.startswith(".")
            and not f.endswith(".tmp")
        ]

        if not media_files:
            logger.info(
                f"UploadPostsPlugin: No pending media files found in queue: {pending_dir}"
            )
            return

        logger.info(
            f"UploadPostsPlugin: Found {len(media_files)} queued media item(s) in {pending_dir}."
        )

        for media_file in media_files:
            try:
                from InstaAddict.core.watchdog import record_heartbeat

                record_heartbeat("upload-posts", f"Processing upload: {media_file}")
            except Exception:
                pass

            base_name = os.path.splitext(media_file)[0]
            media_path = os.path.join(pending_dir, media_file)

            caption = self._extract_caption(
                pending_dir, media_file, config_path, username=username
            )

            # Separate hashtags from narrative text when first-comment mode is active (CO-020)
            hashtag_block_for_comment = ""
            caption_for_composer = caption
            if hashtags_in_comment:
                # Split caption: text lines vs. hashtag lines
                lines = caption.split("\n")
                text_lines = []
                tag_lines = []
                for line in lines:
                    stripped = line.strip()
                    if stripped and all(
                        part.startswith("#") for part in stripped.split() if part
                    ):
                        tag_lines.append(stripped)
                    else:
                        text_lines.append(line)
                caption_for_composer = "\n".join(text_lines).strip()
                hashtag_block_for_comment = " ".join(tag_lines).strip()
                if hashtag_block_for_comment:
                    logger.info(
                        f"First-comment mode: separated {len(tag_lines)} hashtag line(s) from caption."
                    )

            caption_snippet = (
                caption_for_composer[:60] + "..."
                if len(caption_for_composer) > 60
                else caption_for_composer
            )
            logger.info(
                f"Uploading {media_file} with caption: {caption_snippet!r}"
            )
            try:
                from InstaAddict.core.watchdog import record_heartbeat

                record_heartbeat("upload-posts", f"Entering composer for {media_file}")
            except Exception:
                pass
            try:
                success = self._upload_to_ig(
                    device, media_path, caption_for_composer, force_square=force_square
                )
            except Exception as e:
                logger.error(
                    f"Unexpected exception during Instagram upload of {media_file}: {e}",
                    exc_info=True,
                )
                success = False

            if success:
                logger.info(
                    f"Successfully uploaded {media_file}! Archiving media and sidecars to published directory."
                )
                os.makedirs(published_dir, exist_ok=True)

                # Move media file and touch mtime to guarantee rate limit accuracy
                dest_media = os.path.join(published_dir, media_file)
                if os.path.exists(dest_media):
                    try:
                        os.remove(dest_media)
                    except OSError:
                        pass
                shutil.move(media_path, dest_media)
                try:
                    os.utime(dest_media, None)
                except OSError as e:
                    logger.debug(
                        f"Failed to update publication mtime for {dest_media}: {e}"
                    )

                # Move .txt sidecar if present
                txt_path = os.path.join(pending_dir, f"{base_name}.txt")
                if os.path.exists(txt_path):
                    dest_txt = os.path.join(published_dir, f"{base_name}.txt")
                    if os.path.exists(dest_txt):
                        try:
                            os.remove(dest_txt)
                        except OSError:
                            pass
                    shutil.move(txt_path, dest_txt)
                    try:
                        os.utime(dest_txt, None)
                    except OSError:
                        pass

                # Move .json sidecar if present
                json_path = os.path.join(pending_dir, f"{base_name}.json")
                if os.path.exists(json_path):
                    dest_json = os.path.join(
                        published_dir, f"{base_name}.json"
                    )
                    if os.path.exists(dest_json):
                        try:
                            os.remove(dest_json)
                        except OSError:
                            pass
                    shutil.move(json_path, dest_json)
                    try:
                        os.utime(dest_json, None)
                    except OSError:
                        pass

                # Record publication in persistent history ledger (AUDIT-133-G05)
                _record_publication(published_dir, media_file, caption=caption)

                if sessions and len(sessions) > 0:
                    current_session = sessions[-1]
                    if hasattr(current_session, "totalUploadsSuccess"):
                        current_session.totalUploadsSuccess += 1
                    if not hasattr(current_session, "uploadHistory") or current_session.uploadHistory is None:
                        current_session.uploadHistory = []
                    current_session.uploadHistory.append(
                        {
                            "file": media_file,
                            "status": "success",
                            "caption": caption[:100],
                            "timestamp": str(datetime.now()),
                        }
                    )

                # Post hashtags as first comment if flag is set (CO-020 / F-02)
                if hashtags_in_comment and hashtag_block_for_comment:
                    self._post_first_comment(device, hashtag_block_for_comment)

                # Send Telegram notification if configured (pass local path for visual thumbnail)
                try:
                    from InstaAddict.plugins.telegram import (
                        telegram_notify_upload_success,
                    )

                    telegram_notify_upload_success(
                        username, media_file, caption, local_media_path=media_path
                    )
                except Exception as tg_err:
                    logger.debug(
                        f"Failed to send Telegram upload notification: {tg_err}"
                    )
            else:
                logger.error(
                    f"Upload failed for {media_file}. Retaining in pending queue for retry."
                )
                if sessions and len(sessions) > 0:
                    current_session = sessions[-1]
                    if hasattr(current_session, "totalUploadsFailed"):
                        current_session.totalUploadsFailed += 1
                    if not hasattr(current_session, "uploadHistory") or current_session.uploadHistory is None:
                        current_session.uploadHistory = []
                    current_session.uploadHistory.append(
                        {
                            "file": media_file,
                            "status": "failed",
                            "caption": caption[:100],
                            "timestamp": str(datetime.now()),
                        }
                    )

                # Send Telegram failure alert if configured
                try:
                    from InstaAddict.plugins.telegram import (
                        load_telegram_config,
                        telegram_bot_send_text,
                    )

                    tg_conf = load_telegram_config(username)
                    if (
                        tg_conf
                        and tg_conf.get("telegram-api-token")
                        and tg_conf.get("telegram-chat-id")
                    ):
                        fail_msg = (
                            "⚠️ *Instagram Upload Failed!*\n\n"
                            f"📷 *Media*: `{media_file}`\n"
                            "Retaining file in pending queue for retry."
                        )
                        telegram_bot_send_text(
                            tg_conf["telegram-api-token"],
                            tg_conf["telegram-chat-id"],
                            fail_msg,
                        )
                except Exception as tg_err:
                    logger.debug(
                        f"Failed to send Telegram upload failure alert: {tg_err}"
                    )

            # Process exactly one post per plugin invocation
            break

    def _post_first_comment(self, device: Any, hashtag_text: str) -> None:
        """Post hashtags as the first comment on the just-published post (AUDIT-133-G02).

        Navigates to the user's Profile tab, selects the newest post from the grid
        (top-left post, guaranteed to be the user's own post rather than an ad or feed post),
        opens the comment box, types hashtags, and submits.
        All exceptions are swallowed gracefully — a comment failure must never crash an upload.
        """
        if not hashtag_text or not hashtag_text.strip():
            return
        try:
            d = device.deviceV2
            logger.info("First-comment mode: navigating to Profile to safely post hashtag comment on own post...")
            random_sleep(3, 5)

            # Step 1: Navigate to Profile tab
            profile_btn = d(descriptionMatches="(?i).*(Profile|Account|Profile tab).*")
            if not profile_btn.exists(timeout=3):
                profile_btn = d(resourceIdMatches=".*profile_tab.*|.*tab_avatar.*")

            if not profile_btn.exists(timeout=4):
                logger.warning(
                    "_post_first_comment: Profile tab not found. Aborting first comment to prevent commenting on Home feed ads."
                )
                return

            profile_btn.click()
            random_sleep(2, 3)

            # Step 2: Tap the newest post in the user's Profile media grid
            first_grid_item = d(
                resourceIdMatches=".*row_feed_photo_item.*|.*grid_item.*|.*media_image.*|.*image_view.*"
            )
            if not first_grid_item.exists(timeout=4):
                logger.warning(
                    "_post_first_comment: Profile grid items not found. Aborting first comment."
                )
                return

            logger.info("Opening newly published post from Profile grid...")
            first_grid_item.click()
            random_sleep(2, 3)

            # Step 3: Find comment button
            comment_btn = d(descriptionMatches="(?i).*[Cc]omment.*")
            if not comment_btn.exists(timeout=4):
                comment_btn = d(
                    resourceIdMatches=".*row_feed_button_comment.*|.*comment_button.*"
                )
            if not comment_btn.exists(timeout=3):
                logger.debug("_post_first_comment: Comment button not found — skipping.")
                return
            comment_btn.click()
            random_sleep(1, 2)

            # Step 4: Type hashtags into comment box
            comment_input = d(focused=True)
            if not comment_input.exists(timeout=3):
                from InstaAddict.core.resources import ResourceID
                resource_id = ResourceID()
                comment_input = d(resourceId=resource_id.LAYOUT_COMMENT_THREAD_EDITTEXT)
            if not comment_input.exists(timeout=3):
                comment_input = d(
                    resourceIdMatches=".*layout_comment_thread_edittext.*|.*comment_input.*"
                )
            if not comment_input.exists(timeout=3):
                logger.debug("_post_first_comment: Comment input not found — skipping.")
                return

            comment_input.click()
            comment_input.set_text(hashtag_text.strip())
            random_sleep(1, 2)

            # Step 5: Submit the comment
            send_btn = d(descriptionMatches="(?i).*(send|post).*")
            if not send_btn.exists(timeout=3):
                send_btn = d(
                    resourceIdMatches=".*layout_comment_thread_post_button.*|.*comment_post_button.*"
                )
            if send_btn.exists(timeout=3):
                send_btn.click()
                logger.info(f"First comment posted: {hashtag_text[:60]}...")
            else:
                logger.debug("_post_first_comment: Send button not found — comment not submitted.")

            random_sleep(1, 2)
            try:
                d.press("back")
                random_sleep(1, 2)
                d.press("back")
            except Exception:
                pass

        except Exception as e:
            logger.debug(f"_post_first_comment: Non-fatal exception during first comment attempt: {e}")

    def _execute_adb(
        self, serial: str, command_args: List[str], timeout: int = 60
    ) -> bool:
        """Secure isolated execution of ADB commands mapping native array signatures with timeout."""
        cmd: List[str] = ["adb", "-s", serial] + command_args
        try:
            subprocess.run(
                cmd,
                shell=False,
                check=True,
                timeout=timeout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except subprocess.TimeoutExpired:
            logger.error(
                f"ADB execution timed out after {timeout}s: {' '.join(command_args)}"
            )
            return False
        except subprocess.CalledProcessError as e:
            logger.error(
                f"ADB execution failed ({command_args[0]}): Code {e.returncode}"
            )
            return False
        except FileNotFoundError:
            logger.error("ADB executable not found in system PATH.")
            return False

    def _get_mediastore_id(
        self, serial: str, filename: str, is_video: bool = False
    ) -> Optional[str]:
        """Queries Android MediaStore for the newest _id matching pushed media file."""
        uri = (
            "content://media/external/video/media"
            if is_video
            else "content://media/external/images/media"
        )
        cmd = [
            "adb",
            "-s",
            serial,
            "shell",
            "content",
            "query",
            "--uri",
            uri,
            "--projection",
            "_id:_data",
            "--sort",
            "'_id DESC'",
        ]
        try:
            res = subprocess.run(
                cmd, capture_output=True, text=True, check=True, timeout=10
            )
            matching_ids: List[int] = []
            target_fn = filename.lower()
            for line in res.stdout.splitlines():
                if target_fn in line.lower():
                    m = re.search(r"_id=(\d+)", line)
                    if m:
                        matching_ids.append(int(m.group(1)))
            if matching_ids:
                return str(max(matching_ids))
        except Exception as e:
            logger.debug(f"MediaStore query error: {e}")
        return None

    def _detect_media_aspect_ratio(self, media_path: str) -> str:
        """Inspects media dimensions (images and videos) and classifies form factor (AUDIT-133-G03)."""
        if not media_path or not os.path.exists(media_path):
            return "square"

        # Tier 1: Check for video file (.mp4) and parse ISO BMFF track headers
        if media_path.lower().endswith(".mp4"):
            video_dims = _parse_mp4_dimensions(media_path)
            if video_dims:
                width, height = video_dims
                if width > 0 and height > 0:
                    ratio = float(width) / float(height)
                    logger.info(
                        f"Video form factor analysis for {os.path.basename(media_path)}: "
                        f"{width}x{height} (ratio: {ratio:.3f})"
                    )
                    if ratio > 1.05:
                        return "landscape"
                    elif ratio < 0.95:
                        return "portrait"
                    else:
                        return "square"

        # Tier 2: Inspect image dimensions via PIL
        try:
            from PIL import Image

            with Image.open(media_path) as img:
                width, height = img.size
                if width <= 0 or height <= 0:
                    return "square"
                ratio = float(width) / float(height)
                logger.info(
                    f"Media form factor analysis for {os.path.basename(media_path)}: "
                    f"{width}x{height} (ratio: {ratio:.3f})"
                )
                if ratio > 1.05:
                    return "landscape"
                elif ratio < 0.95:
                    return "portrait"
                else:
                    return "square"
        except Exception as e:
            logger.debug(
                f"Failed to inspect media dimensions via PIL for {media_path}: {e}"
            )

        return "square"

    def _adjust_aspect_ratio(self, device: Any, form_factor: str) -> bool:
        """Adjusts the Instagram composer aspect ratio to match the original media form factor.

        Supports both modern Instagram v446+ (Ratio toolstrip -> bottom sheet modal)
        and classic cropper toggle buttons.
        """
        if form_factor == "square":
            logger.info("Media is square (1:1); keeping default square crop.")
            return True

        target_name = "Landscape" if form_factor == "landscape" else "Portrait"
        logger.info(
            f"Preserving original form factor: attempting to set Instagram composer aspect ratio to {target_name}..."
        )

        d = device.deviceV2
        app_id = getattr(device, "app_id", "com.instagram.android")
        res_attr = getattr(device, "ResourceID", None)
        if res_attr is None or isinstance(res_attr, type):
            resource_id = ResourceID(app_id)
        else:
            resource_id = res_attr

        # Tier 1: Modern Instagram v446+ "Ratio" Tool in Horizontal Creation Strip
        try:
            ratio_btn = d(textMatches="(?i)^Ratio$")
            if not ratio_btn.exists(timeout=2):
                ratio_btn = d(descriptionMatches="(?i)^Ratio$")

            # If not immediately visible, attempt a small horizontal scroll on creation toolstrip
            if not ratio_btn.exists(timeout=1):
                h_scroll = d(classNameMatches=".*HorizontalScrollView.*")
                if h_scroll.exists(timeout=1):
                    try:
                        h_scroll.scroll.to(textMatches="(?i)^Ratio$")
                    except Exception:
                        try:
                            h_scroll.swipe("left", steps=10)
                        except Exception:
                            pass
                    if not ratio_btn.exists(timeout=1):
                        ratio_btn = d(textMatches="(?i)^Ratio$")
                    if not ratio_btn.exists(timeout=1):
                        ratio_btn = d(descriptionMatches="(?i)^Ratio$")

            if ratio_btn.exists(timeout=2):
                logger.info("Found 'Ratio' creation tool. Opening aspect ratio bottom sheet...")
                ratio_btn.click()
                random_sleep(1, 2)

                # Find the target option (Landscape or Portrait)
                target_opt = d(textMatches=f"(?i)^{target_name}$")
                if not target_opt.exists(timeout=2):
                    target_opt = d(descriptionMatches=f"(?i)^{target_name}$")

                if target_opt.exists(timeout=2):
                    logger.info(f"Selecting '{target_name}' aspect ratio option...")
                    target_opt.click()
                    random_sleep(0.5, 1.0)
                else:
                    logger.debug(
                        f"Target aspect ratio option '{target_name}' not found in Ratio modal. "
                        "Checking for 'Original' / 'Full size' fallback..."
                    )
                    orig_opt = d(textMatches="(?i)^(Original|Full size|Expand)$")
                    if orig_opt.exists(timeout=1):
                        orig_opt.click()
                        random_sleep(0.5, 1.0)

                # Tap 'Done' button on bottom sheet
                done_btn = d(resourceId=resource_id.BOTTOM_SHEET_DONE_BUTTON)
                if not done_btn.exists(timeout=2):
                    done_btn = d(textMatches="(?i)^Done$")
                if not done_btn.exists(timeout=2):
                    done_btn = d(descriptionMatches="(?i)^Done$")

                if done_btn.exists(timeout=2):
                    done_btn.click()
                    random_sleep(1, 2)
                    logger.info(
                        f"Successfully set composer aspect ratio to {target_name} (Tier 1 Ratio Tool)."
                    )
                    return True
                else:
                    logger.debug("Done button not found; tapping top screen area to close bottom sheet...")
                    try:
                        d.click(0.5, 0.2)
                        random_sleep(1, 2)
                    except Exception:
                        pass
                    return True
        except Exception as e:
            logger.debug(f"Tier 1 Ratio tool selection encountered exception: {e}")

        # Tier 2: Classic Cropper Toggle Button (cropper_toggle_button)
        try:
            cropper_btn = d(resourceId=resource_id.CROPPER_TOGGLE_BUTTON)
            if not cropper_btn.exists(timeout=1):
                cropper_btn = d(
                    resourceIdMatches=".*cropper_toggle_button.*|.*crop_button.*|.*button_crop.*"
                )
            if not cropper_btn.exists(timeout=1):
                cropper_btn = d(
                    descriptionMatches="(?i).*(crop|aspect ratio|full size|expand|fit to screen).*"
                )

            if cropper_btn.exists(timeout=2):
                logger.info("Found classic cropper toggle button. Tapping to toggle aspect ratio...")
                cropper_btn.click()
                random_sleep(1, 2)
                logger.info(
                    f"Successfully toggled aspect ratio for {target_name} (Tier 2 Cropper Toggle)."
                )
                return True
        except Exception as e:
            logger.debug(f"Tier 2 Cropper toggle encountered exception: {e}")

        logger.warning(
            f"Could not locate aspect ratio controls to set {target_name}. "
            "Proceeding with Instagram default framing."
        )
        return False

    def _upload_to_ig(
        self, device: Any, media_path: str, caption: str, force_square: bool = False
    ) -> bool:
        """Drives Instagram composer flow using native ADD_TO_FEED intent and UIAutomator2."""
        serial: str = device.deviceV2.serial
        filename: str = os.path.basename(media_path)
        is_video: bool = filename.lower().endswith(".mp4")
        mime_type: str = (
            "video/mp4"
            if is_video
            else ("image/png" if filename.lower().endswith(".png") else "image/jpeg")
        )
        device_path: str = f"/sdcard/Pictures/{filename}"
        media_id: Optional[str] = None

        try:
            # 1. Push media to device storage
            logger.info(f"Pushing {filename} to device ({device_path})...")
            pushed = self._execute_adb(serial, ["push", media_path, device_path])
            if not pushed:
                logger.error(f"Failed pushing media to device storage: {device_path}")
                return False

            # 2. Trigger media scanner broadcast for indexing
            self._execute_adb(
                serial,
                [
                    "shell",
                    "am",
                    "broadcast",
                    "-a",
                    "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
                    "-d",
                    f"file://{device_path}",
                ],
            )
            random_sleep(1, 2)

            # 3. Query MediaStore ID with retries and content insert fallback
            media_id = self._get_mediastore_id(serial, filename, is_video)
            if not media_id:
                # Fallback insert into MediaStore if broadcast scan did not index immediately
                uri = (
                    "content://media/external/video/media"
                    if is_video
                    else "content://media/external/images/media"
                )
                self._execute_adb(
                    serial,
                    [
                        "shell",
                        "content",
                        "insert",
                        "--uri",
                        uri,
                        "--bind",
                        f"_data:s:{device_path}",
                        "--bind",
                        f"mime_type:s:{mime_type}",
                    ],
                )
                random_sleep(1, 2)
                media_id = self._get_mediastore_id(serial, filename, is_video)

            base_uri = (
                "content://media/external/video/media"
                if is_video
                else "content://media/external/images/media"
            )
            if media_id:
                stream_uri = f"{base_uri}/{media_id}"
            else:
                stream_uri = f"file://{device_path}"

            logger.info(f"Target media stream URI: {stream_uri}")

            # 4. Launch Instagram ADD_TO_FEED intent
            logger.info("Launching Instagram ADD_TO_FEED intent...")
            intent_args = [
                "shell",
                "am",
                "start",
                "-a",
                "com.instagram.share.ADD_TO_FEED",
                "-t",
                mime_type,
                "--eu",
                "android.intent.extra.STREAM",
                stream_uri,
                "-n",
                "com.instagram.android/com.instagram.share.handleractivity.ShareHandlerActivity",
            ]
            launched = self._execute_adb(serial, intent_args)
            if not launched:
                logger.warning(
                    "ADD_TO_FEED launch failed, attempting android.intent.action.SEND fallback..."
                )
                fallback_args = [
                    "shell",
                    "am",
                    "start",
                    "-a",
                    "android.intent.action.SEND",
                    "-t",
                    mime_type,
                    "--eu",
                    "android.intent.extra.STREAM",
                    stream_uri,
                    "-p",
                    "com.instagram.android",
                ]
                self._execute_adb(serial, fallback_args)

            random_sleep(3, 5)

            d = device.deviceV2
            app_id = getattr(device, "app_id", "com.instagram.android")
            res_attr = getattr(device, "ResourceID", None)
            if res_attr is None or isinstance(res_attr, type):
                resource_id = ResourceID(app_id)
            else:
                resource_id = res_attr

            # 4b. Dismiss any initial informational composer modal dialog if present
            ok_btn = d(
                textMatches="(?i)^(OK|Continue|Not now|Got it|Dismiss|Cancel|Maybe later|Skip|Keep editing)$"
            )
            if ok_btn.exists(timeout=2):
                logger.info("Dismissing initial informational composer modal dialog...")
                ok_btn.click()
                random_sleep(1, 2)

            # 4c. Adjust aspect ratio to preserve native form factor (unless force_square is requested)
            if not force_square:
                form_factor = self._detect_media_aspect_ratio(media_path)
                if form_factor in ("landscape", "portrait"):
                    self._adjust_aspect_ratio(device, form_factor)
            else:
                logger.info(
                    "Force square mode active (--upload-force-square); bypassing aspect ratio adjustment."
                )

            # 5. Advance composer steps (Crop/Audio -> Filters -> Share Sheet)
            max_steps = 6
            share_sheet_reached = False
            for step in range(max_steps):
                # Check if Share Sheet is visible
                caption_input = d(resourceId=resource_id.CAPTION_INPUT_TEXT_VIEW)
                share_footer = d(resourceId=resource_id.SHARE_FOOTER_BUTTON)
                if caption_input.exists(timeout=2) or share_footer.exists(timeout=2):
                    logger.info("Reached Instagram post Share Sheet.")
                    share_sheet_reached = True
                    break

                # Check if "Sharing posts" or modal is blocking
                ok_btn = d(
                    textMatches="(?i)^(OK|Continue|Not now|Got it|Dismiss|Cancel|Maybe later|Skip|Keep editing)$"
                )
                if ok_btn.exists(timeout=2):
                    logger.info("Dismissing informational composer modal dialog...")
                    ok_btn.click()
                    random_sleep(1, 2)
                    continue

                # Tap Next button
                next_btn = d(resourceId=resource_id.MEDIA_THUMBNAIL_TRAY_BUTTON)
                if not next_btn.exists(timeout=2):
                    next_btn = d(
                        resourceId=resource_id.MEDIA_THUMBNAIL_TRAY_BUTTON_TEXT
                    )
                if not next_btn.exists(timeout=2):
                    next_btn = d(
                        resourceIdMatches=".*creation_next_button.*|.*next_button.*|.*action_bar_button_action.*|.*action_bar_right_button.*"
                    )
                if not next_btn.exists(timeout=2):
                    next_btn = d(textMatches="(?i)^(Next|>|Share|Continue|Done)$")
                if not next_btn.exists(timeout=2):
                    next_btn = d(descriptionMatches="(?i)^(Next|>|Share|Continue|Done)$")

                if next_btn.exists(timeout=3):
                    logger.info(
                        f"Advancing composer step {step + 1} (tapping Next)..."
                    )
                    next_btn.click()
                    random_sleep(2, 4)
                else:
                    logger.debug(f"Step {step + 1}: Waiting for composer screen...")
                    random_sleep(1, 2)

            if not share_sheet_reached:
                # Check one more time with broad locators
                if (
                    d(resourceId=resource_id.CAPTION_INPUT_TEXT_VIEW).exists(
                        timeout=3
                    )
                    or d(resourceId=resource_id.SHARE_FOOTER_BUTTON).exists(
                        timeout=3
                    )
                    or d(descriptionMatches="(?i)Share").exists(timeout=3)
                ):
                    share_sheet_reached = True

            if not share_sheet_reached:
                logger.error("Failed to navigate to post Share Sheet.")
                return False

            # 6. Set caption if provided
            if caption:
                caption_box = d(resourceId=resource_id.CAPTION_INPUT_TEXT_VIEW)
                if not caption_box.exists(timeout=3):
                    caption_box = d(
                        classNameMatches=".*EditText.*|.*AutoCompleteTextView.*"
                    )

                if caption_box.exists(timeout=5):
                    logger.info(f"Setting post caption ({len(caption)} characters)...")
                    try:
                        caption_box.set_text(caption)
                    except Exception as set_err:
                        logger.warning(
                            f"set_text failed on caption box ({set_err}). Attempting clipboard paste fallback..."
                        )
                        try:
                            d.set_clipboard(caption)
                            caption_box.click()
                            random_sleep(0.5, 1.0)
                            d.paste()
                        except Exception as paste_err:
                            logger.error(f"Clipboard paste fallback failed: {paste_err}")
                    random_sleep(1, 2)
                else:
                    logger.warning(
                        "Caption input field not found on Share Sheet. Proceeding without caption."
                    )

            # 7. Tap Share (with Reels & Feed locators - AUDIT-133-G06)
            share_btn = d(resourceId=resource_id.SHARE_FOOTER_BUTTON)
            if not share_btn.exists(timeout=3):
                share_btn = d(
                    textMatches="(?i)^(Share|Share to Reels|Share Reel|Share to Feed|Post)$"
                )
            if not share_btn.exists(timeout=2):
                share_btn = d(
                    descriptionMatches="(?i)^(Share|Share to Reels|Share Reel|Share to Feed|Post)$"
                )
            if not share_btn.exists(timeout=2):
                share_btn = d(
                    resourceIdMatches=".*share_button.*|.*upload_button.*|.*share_footer_button.*|.*action_bar_button_action.*"
                )

            if share_btn.exists(timeout=5):
                logger.info("Tapping Share button to publish post...")
                share_btn.click()
                logger.info(
                    "Share clicked. Polling for upload completion (max 30s)..."
                )

                # Active verification loop — poll every 3s for up to 30s (CO-022 / F-04)
                _IG_MAIN_ACTIVITIES = {
                    ".activity.MainTabActivity",
                    "com.instagram.mainactivity.MainActivity",
                    "com.instagram.mainactivity.LauncherActivity",
                }
                upload_confirmed = False
                for _tick in range(10):
                    time.sleep(3)
                    try:
                        # Check 1: Home tab visible
                        if d(descriptionMatches="(?i).*Home.*").exists(timeout=1):
                            upload_confirmed = True
                            break
                        # Check 2: Returned to main IG activity
                        cur_app = d.app_current()
                        if cur_app and cur_app.get("activity") in _IG_MAIN_ACTIVITIES:
                            upload_confirmed = True
                            break
                        # Check 3: Progress bar / finalizing overlay gone
                        if not d(resourceIdMatches=".*progress.*").exists(timeout=0):
                            # No progress bar found — may have already completed
                            if d(descriptionMatches="(?i).*Home.*").exists(timeout=1):
                                upload_confirmed = True
                                break
                    except Exception as tick_err:
                        logger.debug(f"Upload poll tick {_tick + 1} error: {tick_err}")

                if upload_confirmed:
                    logger.info("Post uploaded successfully (confirmed).")
                else:
                    logger.info(
                        "Upload completion could not be confirmed within 30s — post likely published."
                    )

                # Post-upload popup sweep (CO-029 / F-02):
                try:
                    from InstaAddict.core.views import UniversalActions
                    UniversalActions.dismiss_dialog(device, max_sweeps=3)
                    random_sleep(1, 2)
                    UniversalActions.dismiss_dialog(device, max_sweeps=2)
                except Exception as dismiss_err:
                    logger.debug(f"Post-upload dialog sweep encountered error: {dismiss_err}")

                return True
            else:
                logger.error("Cannot locate Share button on Share Sheet.")
                return False
        finally:
            # Deterministic device cleanup (AUDIT-133-G07 / R-06)
            self._execute_adb(serial, ["shell", "rm", "-f", device_path], timeout=15)
            if media_id:
                uri = (
                    "content://media/external/video/media"
                    if is_video
                    else "content://media/external/images/media"
                )
                self._execute_adb(
                    serial,
                    ["shell", "content", "delete", "--uri", uri, "--where", f"_id={media_id}"],
                    timeout=10,
                )
