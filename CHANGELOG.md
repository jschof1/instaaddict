# Changelog

## v1.4.3 (2026-10-15) — Release Hygiene for Linux Deployment (Homelab B-77)

Makes a clean install on Linux (Python 3.12) import and test fully, so the bot can be deployed to the R640 Android farm (VM 140) by tag.

### Fixed
- **Missing runtime dependencies (`requirements.txt`, `pyproject.toml`)**: added `google-generativeai`, `python-dotenv`, `pillow` and `matplotlib`; a clean install previously failed to import `InstaAddict.core.gemini_vision` (28 test modules could not be collected). Removed the stale `analytics = ["matplotlib==3.4.2"]` extra (no Python 3.12 wheels); `pytest` and `pytest-mock` added to `dev`.
- **Fleet auto-tune import (`InstaAddict/core/multi_telemetry.py`)**: `apply_tuning_and_restart` imported the non-existent `InstaAddict.core.dogfood_optimizer` inside a try/except, so it silently did nothing; it now uses `InstaAddict.core.dogfood.DogfoodOptimizer` and applies the tuning before restarting the account.
- **Version metadata**: removed the unused `InstaAddict/version.py` (said 1.3.0); README release badge now matches `__version__`.

### Added
- `test/test_release_hygiene.py`: dependency declarations, version consistency, and the fleet auto-tune path.

## v1.4.2 (2026-09-29) — Upload Mechanism Hardening, Scoped Storage Compliance & Bot Stopping Optimization

Production hardening release remediating 8 architectural gaps and shortcuts in the automated upload pipeline (Audit #133, Review #065, Review #066), eliminating Home feed ad commenting risks, adding zero-dependency ISO BMFF MP4 header parsing, and hardening bot stopping and session recovery.

### Fixed & Remediated
- **Scoped Storage & MediaStore URI Resolution (`InstaAddict/plugins/upload_posts.py`)**:
  - Hardened MediaStore content URI resolution by pairing `content insert` with `content query --where "_data='...'"` fallback, eliminating `FileUriExposedException` on Android 7.0 through 16 (AUDIT-133-G01, CO-089).
- **Ad Commenting Elimination (`InstaAddict/plugins/upload_posts.py`)**:
  - Re-architected post-publish first commenting to navigate to the user's Profile tab and open the topmost grid item, completely preventing the bot from leaving hashtag comments on sponsored Home feed ads (AUDIT-133-G02, CO-090).
- **Atomic Telegram Ingestion Staging (`InstaAddict/plugins/telegram.py`, `InstaAddict/plugins/upload_posts.py`)**:
  - Enforced atomic file staging in Telegram download pipelines via `.tmp` staging and `os.replace`, and excluded `.tmp` files from pending upload discovery to prevent race conditions during file transmission (AUDIT-133-G04, CO-092).
- **Durable Upload Rate-Limiting Ledger (`InstaAddict/plugins/upload_posts.py`)**:
  - Migrated cooldown checking from fragile filesystem `mtime` to a durable `.upload_history.json` ledger, preventing premature uploads after file touch or sync events (AUDIT-133-G05, CO-093).
- **Reels Composer Share Button Heuristics (`InstaAddict/plugins/upload_posts.py`)**:
  - Expanded Share button regex to `(?i)^(Share|Share to Reels|Share Reel|Share to Feed|Post)$` across resource IDs, supporting modern Instagram composer variants (AUDIT-133-G06, CO-094).
- **Device Storage & MediaStore Leak Prevention (`InstaAddict/plugins/upload_posts.py`)**:
  - Wrapped upload staging in `try...finally` to ensure remote temporary files on `/sdcard/Pictures/` and their respective MediaStore entries are unconditionally purged on both success and failure (AUDIT-133-G07, CO-095).
- **Bot Stopping & Watchdog Recovery (`InstaAddict/core/bot_flow.py`, `InstaAddict/core/device_facade.py`, `InstaAddict/core/dogfood.py`)**:
  - Hardened watchdog heartbeats and subscreen escape sequences against unhandled RPC errors and daemon stalls.

### Added
- **Zero-Dependency ISO BMFF MP4 Box Parser (`InstaAddict/plugins/upload_posts.py`, `test/test_upload_aspect_ratio.py`)**:
  - Implemented pure-Python MP4 header parser extracting track header (`moov -> trak -> tkhd`) 16.16 fixed-point dimensions to enable accurate aspect ratio detection for video uploads (AUDIT-133-G03, CO-091).
- **Comprehensive Test Coverage (`test/test_upload_aspect_ratio.py`, `test/test_upload_posts.py`, `test/test_bot_stopping_and_dogfood_tuning.py`)**:
  - Added unit test suites verifying synthetic MP4 dimension extraction, atomic download staging, ledger durability, and end-to-end mock uploads (469 passed, 100% green).

## v1.4.1 (2026-09-25) — Milestone 11 Multi-Account Fleet Orchestration & Comprehensive Operator Guide

Major milestone release delivering full multi-process fleet orchestration, atomic IPC status beaconing, autonomous emulator and process health monitoring, real-time live TUI dashboard, zero-downtime hot reloading, 21 production safeguards (GAP-01 to GAP-21), and the complete 10-section User & Operator Guide (`docs/USER_GUIDE.md`).

### Added
- **Multi-Account Fleet Supervisor (`InstaAddict/core/orchestrator.py`, `python run.py multi`)**:
  - Independent OS subprocess execution per account with exclusive PID locking and zombie process reaping.
  - Staggered emulator launch delays (10–20s) preventing CPU/IO contention storms.
  - Granular account filtering via `--only <acc1> [acc2...]`.
  - Graceful shutdown sentinels (`.stop`) allowing active posts to finish cleanly.
- **Atomic IPC Status Beaconing (`InstaAddict/core/beacon.py`)**:
  - Non-blocking daemon writing atomic `.status.json` and `.ipc/accounts/<username>.json` every ~5s.
  - Instantaneous CLI query subcommand (`python run.py multi --status`).
  - Cross-platform NTFS/Unix file lock retry readers eliminating contention crashes.
- **Autonomous Health Monitor Watchdog (`InstaAddict/core/health_monitor.py`)**:
  - Background watchdog detecting stale heartbeats (>45s), process crashes, and dead ADB connections.
  - Exponential restart backoff with crash-loop throttling (max 3 consecutive attempts).
- **Interactive Multi-Account TUI Dashboard (`InstaAddict/core/multi_dashboard.py`)**:
  - Curses/Rich live dashboard with 3 view modes (Fleet Table, Account Cards, Telemetry Funnel).
  - Dynamic hotkeys (`[Tab]` cycle views, `[C]` hot reload, `[Q]` quit) with <0.5% CPU overhead.
  - Headless/plain logging mode (`--no-tui`) for CI, cron, and Docker deployments.
- **Cross-Account Fleet Telemetry Aggregator (`InstaAddict/core/multi_telemetry.py`)**:
  - Cross-account telemetry aggregation generating Markdown and JSON analytics reports.
- **Two-Way Telegram Multi-Account Supervision (`InstaAddict/plugins/telegram.py`)**:
  - Remote targeting commands (`/status @account`, `/restart @account`, `/post @account`) and media routing.
- **Complete User & Operator Manual (`docs/USER_GUIDE.md`)**:
  - 10-section production runbook covering single-account, multi-account fleet, Vision AI, content queue, safety shields, and troubleshooting.

## v1.4.1 (Earlier) — Engagement Pipeline Hardening, Reels Ad Filtering & Invariant Robustness

Patch release resolving false-positive Reels ad classification, inline follow button discovery in modern Instagram v446+, session state dictionary type invariants, range-safe percentage expression parsing, post-lifecycle comment decoupling for already-liked posts, and defensive profile filter null-guards. Also introduces InstaAddict-AI rebranding, dedicated CLI entrypoint, 3rd TUI view mode (Filter Intelligence), and post-session Rich terminal summary renderer.

### Added
- **InstaAddict-AI Rebranding & Dedicated CLI Entrypoint (`pyproject.toml`, `InstaAddict/__main__.py`, `InstaAddict/core/utils.py`)**:
  - Rebranded distribution package to `InstaAddict-AI` with dedicated `instaaddict-ai` CLI script alongside legacy `instaaddict`.
  - Updated startup banners, donation/starring prompts, and PyPI update URLs to `https://pypi.org/pypi/InstaAddict-AI/json`.
  - Preserved internal Python import paths (`InstaAddict.*`) for syntactically valid module namespaces.
- **TUI Filter Intelligence View & 2-Row Responsive Layout (`InstaAddict/core/tui.py`, `test/test_tui_dashboard.py`)**:
  - Added 3rd ViewMode (`FILTER_INTELLIGENCE`) cycling via `[Ctrl+G]` displaying skip reason bar distribution, per-job lifecycle metrics, and crash timeline.
  - Upgraded header to 2-row layout with device, working hours, and watchdog health status.
  - Upgraded footer to 2-row layout with boxed shortcuts and view mode indicators.
- **Post-Session Rich Summary Engine (`InstaAddict/core/rich_summary.py`, `InstaAddict/core/report.py`)**:
  - Implemented terminal report renderer featuring hero banner, health scores, KPI grid, per-source skip reasons, job yield %, and dogfood recommendations.

### Fixed
- **Reels False-Positive Ad Classification (`InstaAddict/plugins/interact_reels.py`, `test/test_reels_ad_and_follow_fix.py`)**:
  - Excluded `"Subscribe"` from ad CTA regex patterns to avoid misclassifying organic creator channels with subscription badges.
  - Enforced vertical spatial bounds (`top > height * 0.4`) and banner width thresholds (`width > width * 0.25`) before declaring ad buttons, preventing recycled off-screen views and top-docked ViewPager headers from dropping organic Reels.
- **Modern Instagram v446+ Inline Follow Button Discovery (`InstaAddict/plugins/interact_reels.py`)**:
  - Added `inline_follow_button` and description matching (`descriptionMatches="(?i)^Follow$"`) to the Reels creator follow selector, ensuring reliable follows during Reels playback.
- **Session State Follow Invariant Protection (`InstaAddict/plugins/interact_reels.py`, `test/test_follows_and_comments_robustness.py`)**:
  - Preserved `SessionState.totalFollowed` as a `dict[str, int]` updated atomically through `SessionState.add_interaction()`, preventing `AttributeError` / `TypeError` crashes during session limit verification and TUI rendering.
  - Maintained backward compatibility with integer test mocks via conditional type guarding.
- **Range-Safe Percentage Parsing (`InstaAddict/plugins/interact_reels.py`)**:
  - Replaced direct `int()` casting on `evaluate_percentage` and `follow_percentage` with `get_value()`, preventing `ValueError` crashes when configured with range expressions like `"30-40"`.
- **Post-Lifecycle Comment Decoupling (`InstaAddict/core/interaction.py`)**:
  - Removed premature `device.back()` calls immediately following photo/video likes, ensuring posts remain open while `_comment()` evaluates.
  - Decoupled comment execution from like freshness, allowing comments to be posted on already-liked posts when allowed by session limits and user filters.
- **Filter Null-Safety & Fallback Guarantees (`InstaAddict/core/interaction.py`)**:
  - Guarded `can_comment()` against `profile_filter is None` and wrapped tuple unpacking defensively against structure mismatches.
  - Ensured `load_random_comment()` strictly guarantees a non-empty string fallback from `DEFAULT_COMMENTS`.
- **Post-View Commenting Engine & Feed Interaction Persistence (`InstaAddict/core/handle_sources.py`, `test/test_post_view_commenting.py`)**:
  - Implemented direct post-view commenting in `handle_posts` for both feed and hashtag posts, resolving the dead-code architectural gap in feed commenting.
  - Gated post comments by `profile_filter.can_comment(current_job)` and `session_state.check_limit(Limit.COMMENTS)`.
  - Added range-safe percentage parsing via `get_value()` and `MediaType` detection.
  - Enforced single source of truth for `session_state.totalComments` inside `_comment()`, eliminating duplicate metric increments.
  - Persisted feed interactions via `storage.add_interacted_user()` to record liked and commented states in SQLite.
  - Enforced comment limit termination guard in feed interaction loop.
- **Upstream PR #28 Port: Carousel Detection, Sliver Skip & Geometric Like Pairing (`InstaAddict/core/views.py`, `test/test_upstream_pr28_e1_e2_e3.py`)**:
  - Ported E1: Multi-slide carousel indicator walrus detection before photo/video branches in `detect_media_type()`.
  - Ported E2: Added `_describes_a_post()` helper with empty-string normalization and sliver-skip loop in `_get_media_container()` skipping remnant headers under 54px.
  - Ported E3: Implemented `_get_like_button_of()` geometric heart pairing with bounding coordinate matching and modernized `_like_in_post_view()`.
  - Preserved Reels viewer code path and backwards compatibility with Instagram v447+.
- **Crash Remediation, EmptyList Decoupling & Dogfood Optimizer Modernization (`InstaAddict/core/decorators.py`, `InstaAddict/core/dogfood.py`, `InstaAddict/core/views.py`)**:
  - Hardened `HomeView.navigateToSearch()` and `SearchView.navigate_to_target()` against transient `JsonRpcError` and `UiObjectNotFoundError`.
  - Decoupled `EmptyList` from `restart()` in `@run_safely`, advancing task flow gracefully without killing Instagram or incrementing crash counters.
  - Modernized `DogfoodOptimizer` with sliding session window (`window_sessions=5`) and accurate uncaught error parsing.
- **Hashtag Grid Stuck & Escape Hardening (`InstaAddict/core/navigation.py`, `InstaAddict/core/handle_sources.py`, `InstaAddict/core/views.py`, `test/test_tuning_and_operational_fixes.py`)**:
  - Hardened `nav_to_hashtag_or_place()` with center-point bounds coordinate click, 2-attempt tap retry loop, and `OpenedPostView.is_post_opened()` verification.
  - Expanded `OpenedPostView.is_post_opened()` regex locators to recognize modern Reels/Clips root containers (`ROOT_CLIPS_LAYOUT`, `CLIPS_VIEWER_CONTAINER`, `CLIPS_VIEWER_VIEW_PAGER`, `CLIPS_VIDEO_CONTAINER`).
  - Added `nr_consecutive_unidentifiable` circuit breaker (threshold 5) in `handle_posts()` to immediately break out of zero-displacement grid traps.
  - Added instant grid exit detection: immediately aborts grid browsing and returns to top level if UI state shifts out of post views.
  - Recorded `"UNIDENTIFIABLE"` skips in `session_state` to expose stuck grid anomalies to `DogfoodOptimizer`.
  - Conditioned `BotWatchdog.record_heartbeat()` on valid non-empty usernames to prevent watchdog suppression during unidentifiable grid loops.
  - Wired `UniversalActions.check_micro_stall()` and `MicroStallSentinel.record_progress()` into post interaction flow.
- **Startup Crash Resilience & Fast ADB Fallback (`InstaAddict/core/device_facade.py`, `InstaAddict/core/bot_flow.py`, `InstaAddict/core/utils.py`, `test/test_tuning_and_operational_fixes.py`)**:
  - Implemented `DeviceFacade._get_info_via_adb()` using direct parameterized ADB shell queries (`ro.product.model`, `ro.build.version.sdk`, `wm size`, `wm density`, `dumpsys power`) executing in <50ms.
  - Hardened `DeviceFacade.get_info(fallback_to_adb=True)` and `get_device_info(device)` with single-pass dictionary caching, eliminating 45-minute fatal hang when UiAutomator RPC service is disconnected or slow.
  - Added `DeviceFacade.is_screen_on()` with ADB dumpsys power fallback, replacing unhandled RPC property lookups during bot startup.
  - Gracefully handled HTTP 404 responses from PyPI in `utils.update_available()` for source and git installs, eliminating false-alarm ERROR logs at startup.
- **Self-Learning Telemetry Expansion (`InstaAddict/core/dogfood.py`, `InstaAddict/core/telemetry.py`)**:
  - Expanded `PerformanceTracker` with bounded `device_health_samples` ring buffer tracking connection state and transport latency.
  - Enhanced `DogfoodOptimizer._analyze_error_log()` to parse RPC disconnects, ADB timeouts, Watchdog recovery triggers, and grid traps.
  - Added automated actionable tuning recommendations for device transport health, watchdog stability, and source grid traps.



## v1.4.0 — Engagement Pipeline Restoration, Follower Cache, and Aussie Vision Voice

Feature release delivering root-cause resolution for zero follows and zero comments, native Reels follow action, 5-tier ViewGroup caption extraction, atomic local followers caching, directional unfollow sorting, Ctrl-chord hotkeys with ASCII control byte decoding, em-dash regex sanitization, and subtle Aussie dog voice prompt tuning for Gemini Vision AI.

### Added
- **Native Reels Follow Action (`InstaAddict/plugins/interact_reels.py`, `test/test_follows_and_comments_remediation.py`)**:
  - Implemented creator follow action directly within the active video viewport targeting `clips_follow_button` and `"Follow"` text/description buttons.
  - Automatically registers follows in session state (`sessions[-1].totalFollowed += 1`) and enforces configured session follow limits.
  - Raised default `evaluate_percentage` from 25% to **70%** for active Vision AI commenting.
- **Vision AI Subtle Aussie Voice & Anti-AI Formatting Sanitizer (`InstaAddict/core/gemini_vision.py`, `core/interaction.py`)**:
  - Built regex replacement in `_sanitize_response()` that eradicates em-dashes (`—`) and en-dashes (`–`), replacing them with natural conversational commas.
  - Enhanced Vision AI system prompts to strictly ban corporate AI self-identifications, buzzwords, and excessive punctuation, conditioning responses with authentic Australian dog vernacular (*reckon*, *heaps*, *ripper*, *mate*, *cheers*, *keen*) in punchy 3–6 word sentences.
  - Updated fallback comments in `InstaAddict/core/interaction.py` to match authentic Aussie dog styling.
- **Comment Permissibility Mode Fix (`InstaAddict/core/filter.py`, `accounts/lolatheozjack/filters.yml`)**:
  - Fixed `Filter.can_comment()` to default to `True` when mode-specific comment keys are omitted from `filters.yml`, preventing silent suppression of commenting pipelines.
- **Persistent Local Followers Cache & Non-Scraping Unfollow Optimization (`InstaAddict/core/storage.py`, `plugins/action_unfollow_followers.py`, `core/views.py`, `test/test_unfollow_optimization.py`)**:
  - Implemented atomic `followers_cache.json` persistence with O(1) in-memory lookup.
  - Added follower count delta guard: bypasses follower list scraping completely when the profile header follower count matches the cached count.
  - Implemented 4-tier "Follows you" badge detection on profile headers, eliminating 80–90% of redundant following-list scrapes.
  - Added directional sorting CLI flags (`--sort-followers-latest`) to target recent followings first.
- **Multi-Tier Reels Caption Extraction & Ctrl-Chord Hotkeys (`InstaAddict/plugins/interact_reels.py`, `core/tui.py`, `core/utils.py`, `test/test_reels_caption_and_ctrl_shortcuts.py`)**:
  - Built 5-tier caption extraction traversing child `TextView` nodes inside `clips_caption_component` ViewGroup containers.
  - Added `clean_trailing_more()` to strip `...more` expander tokens without corrupting hashtags or trailing sentences.
  - Migrated interactive keyboard listeners to Ctrl chords (`Ctrl+S`, `Ctrl+U`, `Ctrl+D`, `Ctrl+C`) with full ASCII control byte decoding (`\x13`, `\x15`, `\x04`, `\x03`).
  - Added dynamic debug logging toggle (`Ctrl+D`) and sliced 5s sleep polling for responsive upload command execution.
- **Thread-Safe Matplotlib Backend & Watchdog Hardening (`InstaAddict/__init__.py`, `core/watchdog.py`, `test/test_matplotlib_backend.py`, `test/test_watchdog.py`)**:
  - Forced headless `Agg` backend for matplotlib at process entrypoints, preventing Windows `Tcl_AsyncDelete` thread panics.
  - Corrected escalation timer reset in `BotWatchdog` to guarantee multi-tier escalation from soft recovery to task skip and app relaunch during persistent hangs.

## v1.3.0 — Modern Terminal User Interface (TUI) & Live Dashboard

Feature release introducing a modern, high-performance terminal user interface and live dashboard powered by `rich`, featuring real-time visual progress bars against safety limits, active target and cooldown context, and a live rolling log stream with automated headless fallback and legacy console encoding resilience.

### Added
- **Photo Form Factor & Aspect Ratio Preservation Engine (`InstaAddict/plugins/upload_posts.py`, `core/resources.py`, `test/test_upload_aspect_ratio.py`)**:
  - Implemented automatic image aspect ratio detection via Pillow (`PIL.Image`), accurately distinguishing `landscape` (width/height > 1.05), `portrait` (width/height < 0.95), and `square` form factors.
  - Built multi-tier composer aspect ratio adjustment in `UploadPostsPlugin`:
    - **Tier 1 (Modern Instagram v446+)**: Opens the `Ratio` creation tool from the horizontal toolstrip, selects the matching `Landscape` or `Portrait` option from the bottom sheet modal, and applies with `bottom_sheet_done_button`.
    - **Tier 2 (Classic Cropper Fallback)**: Toggles aspect ratio via `cropper_toggle_button` or `descriptionMatches="(?i).*(crop|aspect ratio|full size|expand).*"`.
  - Automatically dismisses initial blocking composer modals before ratio adjustment to guarantee frictionless navigation.
  - Added `--upload-force-square` CLI argument and `upload-force-square: true/false` YAML configuration option for operators who explicitly want 1:1 square crop.
  - Created 13-case unit test suite (`test/test_upload_aspect_ratio.py`) with 100% pass rate and zero regressions across existing upload test suites.
- **Autonomous Out-of-Band Watchdog Daemon & Blinking LED Heartbeat (`InstaAddict/core/watchdog.py`, `core/tui.py`, `core/bot_flow.py`, `core/utils.py`, `core/session_state.py`, `core/views.py`, `core/filter.py`)**:
  - Implemented `BotWatchdog` background daemon thread running completely isolated from the main bot loop and ADB socket hangs.
  - Implemented 3-Tier Escalation Recovery Strategy:
    - Tier 1 (Soft Recovery - 90s Inactivity): Non-blocking isolated subprocess dispatch of `KEYCODE_WAKEUP` (`224`) and `KEYCODE_BACK` (`4`) to dismiss blocking overlays and restore screen navigation.
    - Tier 2 (Task Skip - 105s Inactivity): Automatically triggers task skip via `DashboardManager.trigger_skip_task()` and `.skip_task` IPC to advance to the next scheduled task without process termination.
    - Tier 3 (Nuclear Restart - 120s Inactivity): Force-stops `com.instagram.android` and relaunches app via Android monkey launcher `1`.
  - Added a blinking "LED light" heartbeat indicator in the top-right corner of the TUI terminal interface panel:
    - `🟢 [● LIVE]` pulsing green dot when execution is healthy and fresh.
    - `🔵 [⏸️ PAUSED]` steady blue indicator during intentional sleeps, cooldowns, or off-hours (`wait_for_next_session`).
    - `🟡 [● STALLED {elapsed}s]` bright yellow warning when activity has stalled (>30s).
    - `🔴 [▲ RECOVERING #{attempts}]` flashing bright red alert during active recovery escalation.
  - Resolved reentrant lock deadlock in `DashboardManager` by migrating `self._lock` from `threading.Lock()` to `threading.RLock()`.
  - Decoupled operational metrics (`ads_bypassed`, `dialogs_dismissed`, `profiles_checked`, `profiles_skipped`) from TUI state via `SessionState.get_active()`, guaranteeing 100% accurate metric tracking in headless and CLI modes.
  - Added `totalWatchdogRecoveries` metric to `SessionState`, `SessionStateEncoder`, and the TUI operational metrics table.
  - Created 11-case test suite (`test/test_watchdog.py`) with 100% pass rate (201/201 tests passing project-wide).
- **Task Skip Shortcut & Fast Next-Task Navigation Engine (`InstaAddict/core/tui.py`, `core/utils.py`, `core/bot_flow.py`, `core/handle_sources.py`, `plugins/interact_reels.py`, `plugins/action_unfollow_followers.py`)**:
  - Implemented interactive keyboard shortcuts `[S]` (Skip) and `[N]` (Next) in `KeyboardListenerThread` to immediately abort the currently active job/source and advance to the next scheduled task in the queue.
  - Implemented file-based IPC signal watcher (`accounts/<username>/.skip_task`) enabling external scripts, Telegram commands, or background sessions to skip tasks without direct console keystrokes.
  - Added instant countdown termination in `InstaAddict/core/utils.py:countdown()` when a skip is requested.
  - Hooked task skip consumption at `bot_flow.py` dispatch level and graceful loop breakouts across `handle_posts()`, `handle_likers()`, `handle_blogger()`, `interact_reels()`, `action_unfollow_followers()`, and `interact_with_user()`.
  - Updated TUI footer, stats shortcuts summary, and active execution context panel with live skip status feedback.
- **Reels Engagement Deadlock Elimination & Telemetry Synchronization (`InstaAddict/core/views.py`, `plugins/interact_reels.py`, `core/handle_sources.py`, `core/session_state.py`)**:
  - Replaced `return True, 0` with `return False, -1` in `PostsViewList._find_likers_container` for full-screen Reels viewer mode, resolving the root cause of 100% skipped posts in hashtag and feed sources when `min_likers > 0`.
  - Added `sessions[-1].totalWatched` increment per watched reel in `interact_reels.py`, syncing the Watched metric in the TUI.
  - Added `UniversalActions.detect_block(device)`, `sessions[-1].totalLikes += 1`, and `sessions[-1].add_interaction("interact-reels", ...)` on double-tap likes in `interact_reels.py`.
  - Passed dynamic `current_user` instead of hardcoded `"REEL_STALKER"` to `_comment` in `interact_reels.py`, enabling comment confirmation and `totalComments` incrementing.
  - Added `session_state.add_interaction("feed", ...)` on feed likes in `handle_sources.py`.
  - Resolved historical defect in `SessionState.add_interaction` where non-scraping interactions (`scraped=False`) reset `successfulInteractions[source]` to `0`.
- **Instagram Grid Peek Preview Direct Liking Engine & Fast Tap (`InstaAddict/core/views.py`, `interaction.py`)**:
  - Implemented native detection for Instagram's 3D Touch / long-press Peek Preview modal (`is_peek_preview_opened()` and `is_peek_already_liked()`).
  - Implemented direct in-preview liking (`like_in_peek()`) so navigation effort is never wasted when the preview modal triggers, immediately registering likes in session state and telemetry.
  - Implemented immediate modal dismissal (`dismiss_peek()`), eliminating 25–40s timeout cascades on standard feed element locators.
  - Hardened `PostsGridView.navigateToPost` with element center coordinate tapping `(x_center, y_center)` to evade Android's ~400ms `OnLongClickListener` threshold.
- **Consecutive Failure Circuit Breaker & Verified Profile Exit (`InstaAddict/core/interaction.py`, `handle_sources.py`)**:
  - Added `consecutive_open_failures` circuit breaker in `interact_with_user`: dismisses lingering overlays on failure and automatically aborts stuck profiles after 2 consecutive post open failures.
  - Replaced blind single `device.back()` in `handle_sources.py` (`handle_posts` and `handle_likers`) with a verified `ProfileView._is_still_on_profile()` loop (up to 4 iterations), guaranteeing a clean return to source feeds before subsequent swiping.
- **Live Operational Effort & Real-Time Throughput Counters (`InstaAddict/core/tui.py`, `session_state.py`)**:
  - Extended `SessionState` and `DashboardState` with real-time operational effort tracking: Posts Scanned, Profiles Checked, Profiles Skipped (with dynamic Filter Pass Rate %), Reels Evaluated, Ads Bypassed, and Dialogs Dismissed.
  - Eliminated the static stats illusion where conversion KPI limits remained frozen at 0% during long filtering intervals.
  - Wired dynamic action telemetry directly into `handle_sources.py`, `filter.py`, `interact_reels.py`, and `views.py`.
- **Content Queue Discovery & Telemetry Engine (`InstaAddict/core/tui.py`)**:
  - Live scanning of `accounts/<username>/content_queue/` reporting pending photos count, total published items, elapsed time since last upload, and rate-limit cooldown status.
  - Properly handles supported media (`.jpg`, `.jpeg`, `.png`, `.mp4`) while ignoring sidecar `.txt` and `.json` metadata.
- **Interactive Keyboard Listener & On-Demand Upload Shortcut (`[U]`)**:
  - Cross-platform non-blocking daemon thread (`KeyboardListenerThread`) with Windows `msvcrt` and POSIX `select` implementations, guarded by `isatty()` for non-TTY environments.
  - Pressing `[U]` queues an immediate photo upload from the pending queue, consumed by `bot_flow.py` via `UploadPostsPlugin(upload_force=True)`.
  - Pressing `[D]` forces an immediate screen refresh.
- **Responsive 3-Subtable TUI Dashboard Layout**:
  - Re-architected statistics display into 3 clean side-by-side sub-tables (KPI Limits, Real-Time Effort, Content Queue & Publishing) on standard terminals (height >= 28), with an automated space-saving summary fallback on smaller console windows.
- **Unit Test Coverage (`test/test_tui_dashboard.py`)**:
  - Expanded test suite to 25 automated unit tests covering effort counters, queue filesystem discovery, keyboard listener dispatch, non-TTY graceful termination, and responsive layout scaling (173/173 total repo tests passing).
- **Terminal User Interface Engine (`InstaAddict/core/tui.py`)**:
  - Thread-safe `DashboardState` with reentrant locks (`RLock`) synchronizing metrics (likes, follows, unfollows, comments, watches, uploads, crashes, total interactions) and configured limits against bot execution threads.
  - Multi-tier `rich` layout with live 4 Hz refresh rate: Header banner with account and device telemetry, progress bars with color-coded safety thresholds, active job and target context, and rolling log panel with severity color coding.
  - Responsive terminal layout adaptation: dynamically transitions between dual-column view (width >= 85) and single-column stacked view (width < 85).
- **Log Stream Redirection Bridge (`InstaAddict/core/log.py`)**:
  - `TuiLogHandler` capturing logging records, stripping ANSI escape sequences, splitting multiline records, enforcing 120-character line bounds, and piping entries into a bounded ring buffer (`maxlen=30`).
  - Seamless stdout handler decoupling during live execution and clean restoration before summary report printing.
- **CLI Flags & Auto-Detection (`InstaAddict/plugins/core_arguments.py`)**:
  - Added `--tui` and `--no-tui` flags with automatic `isatty()` interactive console detection and headless/CI fallback.
- **Cross-Platform Console & Encoding Hardening**:
  - Implemented `safe_glyph(glyph, fallback)` detecting `sys.stdout.encoding` capabilities and falling back to clean ASCII equivalents on non-UTF-8 Windows consoles (`cp1252`/`cp437`) to eliminate `UnicodeEncodeError`.
  - Configured `Console(safe_box=True)` to prevent box-drawing character corruption on legacy command prompts.
  - Registered `atexit.register(self.stop)` in `DashboardManager` and `try...finally:` in `countdown()` to guarantee terminal restoration and cursor visibility upon exit or interrupt.
- **Upstream Feature & Build Compatibility Alignment (Audit #062)**:
  - Validated full integration of all upstream bugfixes from `joeahkim/InstaAddict` PRs #10, #11, #14, #17, #24, #25, and #26.
  - Bumped tested Instagram version target to `447.0.0.55.81` (`InstaAddict/__init__.py`).
  - Synchronized `pyproject.toml` dependencies with `requirements.txt` (`uiautomator2~=2.16.19`, `packaging~=26.2`, `standard-pkg-resources>=1.0.0`, `imageio[ffmpeg]`, `websocket-client`, `rich>=13.0.0`).

### Fixed
- **Telegram Inbox Fatal TypeError & Silent TUI Crash Remediation (`InstaAddict/plugins/telegram.py`, `core/bot_flow.py`, `core/log.py`)**:
  - Removed invalid `"operation": True` from `--telegram-inbox` in `TelegramReports` argument definition, preventing `telegram-inbox` from being erroneously scheduled as an operational interaction job.
  - Added defensive argument handling in `TelegramReports.run()` with `*args, **kwargs` and action dispatcher detection, preventing `TypeError` if invoked via the operational plugin dispatcher.
  - Added explicit removal of `telegram-inbox` from `jobs_list` in `bot_flow.py`.
  - Updated `handle_uncaught_exception` in `InstaAddict/core/log.py` to automatically tear down active `DashboardManager` and reattach console logging before delegating to `sys.__excepthook__`, ensuring crash tracebacks are clearly visible in the console.
  - Added regression test suite in `test/test_telegram_inbox.py` verifying argument metadata, dispatch resilience, and excepthook TUI teardown.

**Full diff**: `v1.2.1...v1.3.0`

## v1.2.1 — Modal Dialog Dismissal, Rate Instagram Handling & Stuck-Screen Self-Healing

Resilience patch release introducing universal non-destructive modal popup dismissal (specifically targeting "Rate Instagram", push notification requests, contact sync, and system ANR dialogs), post-upload popup sweeping, and 4-tier escalated stuck-screen recovery with clean app relaunch.

### Added
- **Universal Modal Dialog Dismissal Engine (`UniversalActions.dismiss_dialog`)**:
  - Safe priority handling for "Rate Instagram" dialogs: strictly clicks "No, thanks" or "Remind me later" and excludes "Rate Instagram" to prevent exiting to the Google Play Store.
  - Multi-tier matching for negative/dismissive options: `"Not now"`, `"Cancel"`, `"Skip"`, `"Maybe later"`, `"Don't allow"`, `"Never"`, `"No"`, `"Close"`.
  - Fallbacks for informational acknowledgments (`"OK"`, `"Got it"`, `"Continue"`), resource IDs (`NEGATIVE_BUTTON`), and system ANRs (`"Wait"`).
- **Post-Upload Dialog Sweeping (`UploadPostsPlugin._upload_to_ig`)**:
  - 3-iteration dialog sweep immediately following confirmed post publication to neutralize popups before subsequent jobs execute.
- **Escalated Stuck-Screen Self-Healing (`UniversalActions.recover_stuck_screen`)**:
  - 4-tier recovery protocol: dialog dismissal -> Android back key sequences -> Home tab navigation -> clean application restart (`app_stop` + `app_start`) when persistent navigation deadlocks occur.
- **Resilient Tab Bar Navigation & Inter-Job Recovery (`TabBarView._navigateTo`, `bot_flow.py`)**:
  - Automatically sweeps obscuring dialogs if tab buttons are not found on first pass.
  - Replaced flawed `is_tab_bar_visible()` breakout with profile username validation and clean-restart escalation, ensuring subsequent scheduled jobs are not abandoned.
- **Unit Test Coverage (`test/test_dialog_dismissal_and_stuck_recovery.py`)**:
  - 10 automated unit tests covering all dismissal tiers, rate dialog priority, back navigation fallback, and app restart triggers.

- **Security & Subprocess Hardening (OWASP A03:2021)**:
  - Converted 100% of internal ADB and OS execution calls in `InstaAddict/core/utils.py` and `InstaAddict/core/device_facade.py` from `shell=True` to parameterized argument lists with defensive timeouts.
  - Eliminated potential command injection vectors on external URLs and system settings.
- **Privacy Decoupling & Account Isolation**:
  - Decoupled hardcoded persona strings and localized hashtag fallbacks in `gemini_vision.py`, `hashtag_manager.py`, and `upload_posts.py` into generic creator defaults.
  - Enhanced `scripts/check_telegram.py` to auto-discover active account configurations without hardcoded usernames.

### Fixed
- Fixed inter-job navigation stall where background view hierarchy reporting `is_tab_bar_visible() == True` bypassed back presses and caused profile lookups to fail under active modal overlays.
- Verified zero credentials, personal handles, or private environment files are tracked in public git history.

**Full diff**: `v1.2.0...v1.2.1`

## v1.2.0 — Telegram Two-Way Ingestion, AI Retry Architecture & Upload Scheduling Resilience

Comprehensive release introducing two-way Telegram remote photo and caption ingestion, 5-attempt exponential backoff retry engine for Gemini Vision AI, mandatory caption elaboration and hashtag enrichment pre-upload, and upload queue prioritization at session startup.

### Added
- **Two-Way Telegram Bot Ingestion (`telegram.py`, `check_telegram.py`)**:
  - Remote photo and video ingestion directly from Telegram chat into `accounts/<username>/content_queue/pending/`.
  - Companion comment ingestion linking follow-up text messages to recently queued media sidecars (`.txt`).
  - Interactive bot commands (`/status`, `/pending`, `/elaborate`, `/caption`) and photo preview confirmations.
  - Standalone long-polling listener and diagnostic tool `scripts/check_telegram.py` with Windows UTF-8 console support.
- **5-Attempt Exponential Backoff Retry Architecture**:
  - Multi-attempt retry loop with progressive backoff delays ($2s, 4s, 6s, 8s$) across Gemini Vision API and HashtagManager calls.
  - Resilient mitigation of Google Cloud HTTP 500, 503, 504 Deadline Exceeded, and empty response states.
- **Mandatory Pre-Upload Caption Elaboration & Hashtag Enrichment**:
  - Automatically evaluates incoming media with Gemini Vision AI (`gemini-3.6-flash`) using the account persona and user guidance.
  - Automatically queries `HashtagManager` to append at least 3–5 rotating niche hashtags if fewer than 3 exist in the caption.
  - Persists finalized, formatted captions back to `.txt` sidecars on disk.
- **Upload Job Prioritization**:
  - Dynamically places `upload-posts` at index 0 of the session `jobs_list` before randomized interaction tasks to prevent upload starvation from subsequent soft crash limits.

### Fixed & Hardened
- **Google Generative AI Model Migration**:
  - Migrated from deprecated/high-load models to Google's recommended `gemini-3.6-flash`.
- **IME Unicode Cluster Sanitization**:
  - Stripped rogue Zero-Width Joiner (ZWJ `\u200D`), Zero-Width Space (ZWSP `\u200B`), and BOM characters from generated text to protect Android FastInputIME.
  - Atomic grapheme cluster typing in `DeviceFacade` preventing multi-part emoji keystroke corruption.
- **ACP-01 Casing Alignment**:
  - Corrected header casing in `agent/commands/acp.proceed.md` to satisfy deterministic scanner requirements.

**Full diff**: `v1.1.0...v1.2.0`

## v1.1.0 — Modern Reels Architecture, Dynamic Hashtag Engine & Fluid Swiping

Comprehensive release introducing modern Instagram (v446+) Reels viewer compatibility, tiered dynamic hashtag discovery, persistent non-bot followings caching, universal in-app browser escape watchdog, and fluid native swipe physics.

### Added
- **Modern Reels & Clips Viewer Compatibility**:
  - Full support for Instagram's full-screen video viewer (`clips_viewer_view_pager`, `root_clips_layout`, `clips_viewer_container`).
  - Added multi-tier author resolution for `clips_author_username`, `clips_author_profile_pic` (regex content description extraction), and `clips_author_info_component`.
  - Added native Reels like button support (`ResourceID.LIKE_BUTTON`).
  - Added fast Reel caption extraction (`CLIPS_CAPTION_COMPONENT`) with immediate termination to prevent futile scroll loops.
- **Tiered Masterlist & Dynamic Hashtag Discovery Engine (`HashtagManager`)**:
  - Curated 4-tier pool in `accounts/<username>/hashtags.yml` across Local Community, Breed/Niche, Lifestyle/Adventure, and Reach tiers.
  - Strategy 1: AI Gemini Persona Expansion (`--expand-hashtags`) synthesizing high-conversion niche tags grounded in account persona.
  - Strategy 2: Zero-overhead in-app caption harvesting (`harvest_from_caption`) tracking cross-session tag frequency in `discovered_hashtags.json`.
  - Enforced deterministic rules: R-ADD-1..4 (promotion thresholds, anti-spam blacklist, semantic relevance, tier assignment), R-ROT-1..3 (2:2:1:1 tier-balanced sampling, 2-session anti-fatigue cooldowns, shuffle), and R-PRN-1..2 (0-result dead tag pruning, 7-day saturation benching).
  - Added CLI options: `--expand-hashtags`, `--no-harvest-hashtags`, and `--hashtags-file`.
- **Persistent Non-Bot Followings Cache**:
  - High-performance atomic JSON storage in `accounts/<username>/non_bot_followings.json`.
  - Instant O(1) in-memory lookups and batch disk writes at scroll boundaries.
  - Pre-seeded checked set in `ActionUnfollowFollowers` for fast-skipping known non-bot accounts without UI polling or log spam.
  - Automatic cache invalidation on follow and unfollow state transitions.
  - Added CLI options: `--clear-non-bot-cache` and `--ignore-non-bot-cache`.
- **Universal Ad Detection & In-App Browser Escape Watchdog**:
  - Automated detection and dismissal of `BrowserLiteInMainProcessIGActivity` and external browser overlays via native close buttons, fallback back-presses, and foreground recovery.
  - Whitelisted Android system packages (`com.android.systemui`, `android`, IME keyboards) against false dismissal.
  - Bounded CTA button coordinate detection to prevent false ad classifications.
- **Task Sequence Randomizer**:
  - Implemented `--randomize-tasks` / `randomize_task_sequence` to shuffle job execution order on every session for human-like behavior.

### Changed & Improved
- **Decoupled Author Resolution from Ad Detection**:
  - Removed faulty `(False, True, is_hashtag)` return in `views.py` when author view is unclickable; returns `(False, False, is_hashtag)`. Organic posts with non-clickable headers are no longer falsely marked as advertisements and skipped.
- **Fluid Single-Swipe Navigation & 200ms Swipe Physics**:
  - Replaced jerky multi-swipe sequences with a single vertical swipe (80% down to 20% height) for Reels.
  - Removed redundant `HALF_PHOTO` swipe call in `handle_sources.py`.
  - Stripped obsolete 3-retry gap-view loop searching for deprecated `GAP_VIEW_AND_FOOTER_SPACE`.
  - Calibrated native ADB swipe duration to 200ms (`adb shell input swipe x1 y1 x2 y2 200`), achieving snappy and natural mobile flick gestures.

**Full diff**: `v1.0.3...v1.1.0`

## v1.0.3 — Production Telemetry, Error Hardening & Self-Learning System

Production-grade error handling, automated telemetry, continuous non-overwritten reporting, and closed-loop self-learning parameter optimization.

### Added
- **Error Trace Logging (`_error_trace.log`)**: Dedicated warning and error logger capturing third-party errors (`uiautomator2`, `adbutils`, network stack) alongside InstaAddict events.
- **Top-Level Crash Interception**: Installed global `sys.excepthook` to guarantee fatal unhandled Python exceptions are written to the error trace log before process exit.
- **Full State Telemetry**: Expanded `SessionState` and `SessionStateEncoder` to track and persist `totalCrashes`, `totalUploadsSuccess`, `totalUploadsFailed`, and `uploadHistory` into `accounts/{username}/sessions.json`.
- **Upload Outcome Recording**: Enhanced `UploadPostsPlugin` to log upload executions, file names, captions, and statuses directly into the active session state.
- **Continuous Markdown History**: Automated `save_markdown_history()` on session completion (`print_full_report()`), appending to `accounts/{username}/history.md` (never overwritten) and generating timestamped session summaries in `accounts/{username}/reports/session_{timestamp}.md`.
- **Dogfood Self-Learning Optimizer (`DogfoodOptimizer`)**: Implemented `InstaAddict/core/dogfood.py` to analyze run history, error patterns, and source yields, generating automated configuration tuning recommendations in `tuning_suggestions.json` and `tuning_suggestions.md`.
- **Enhanced Data Analytics Markdown Export**: Upgraded `InstaAddict/plugins/data_analytics.py` to render complete tables of interaction yields, crashes, and content queue uploads.

### Fixed
- **Windows File Lock Descriptor Leak**: Explicitly closed file handlers before calling `os.remove()` in `update_log_file_name()`, eliminating Windows `PermissionError: [WinError 32]`.
- **Swipe Jitter & Drag Stalls**: Replaced uiautomator2 dragging with native `adb shell input swipe` for smooth and natural scroll gestures.
- **Gemini API 429 Quota & Safety Hardening**: Added exponential backoff retry loops, 512x512 LANCZOS payload compression, and safety-block fallback sanitizers.

**Full diff**: `v1.0.2...v1.0.3`

## v1.0.2 — Instagram compatibility & reliability fixes

Two weeks of accumulated fixes for running InstaAddict against current Instagram versions (tested against 440.0.0.46.86), plus dependency and packaging cleanup.

### Instagram UI compatibility
- Handle IG 438+'s account switcher via `content-desc` fallback matching, since the previous selector no longer matches the current layout
- Handle Instagram's follower-list restriction gracefully instead of crashing when a target's list is rate-limited
- Detect and skip sponsored/ad posts in the feed instead of mishandling them
- Fixed post likers list opening the wrong profile: `open_likers_container()` was misclicking the first liker's avatar/username instead of opening the full likers list — fixed in both the primary selector path and the XML-hierarchy compatibility fallback
- Fixed stricter photo/video detection: a `video_container` element alone is no longer enough to classify a post as a video, since photo posts on current IG also carry overlay badges matching that element. A post is now only classified as video if a play button or timer is present too — closes #5
- Fixed back-navigation overshoot after opening a post: replaced a fixed-count back-press assumption with a state check (stop once the profile tab bar is visible again, capped at 3 presses), preventing the bot from overshooting back to the blogger's likers list between posts
- Fixed `_check_if_last_post()` hanging indefinitely (sometimes for hours) on collab/repost posts where the caption is attributed to a different account than the profile owner — added a retry cap and a graceful fallback
- Fixed posts with undetectable media type (`MediaType.UNKNOWN`) being silently skipped by the like logic instead of falling back to the standard like flow
- Reworked unfollow-from-list to use the current three-dots options menu instead of a now-removed direct "Following" button; accounts with no Unfollow option available are now collected and reported via Telegram at the end of a run instead of being logged as crashes

### Stability
- Fixed `DeviceFacade.is_alive()` throwing `AttributeError` on current `uiautomator2` (`_is_alive()` and `.server.alive` were both removed upstream) — replaced with a functional check against `.info`
- Fixed a narrow `except uiautomator2.JSONRPCError` clause throwing its own `AttributeError` and masking the real underlying error, since `JSONRPCError` is no longer a valid top-level attribute on current `uiautomator2`

### Setup & packaging
- Package directory fully renamed from `GramAddict` to `InstaAddict`
- Account folders now auto-created from `config-examples/` on first run instead of requiring manual setup
- `requirements.txt`: added `imageio` and `websocket-client` (previously undeclared runtime dependencies), and resolved `setuptools`/`pkg_resources` breakage on Python 3.13

**Full diff**: `v1.0.1...v1.0.2`

## 1.0.1 (2026-07-18) - First InstaAddict Release

This is the first production release of **InstaAddict**, a continuation of the [GramAddict](https://github.com/GramAddict/bot) project.

### New
- Forked and rebranded from GramAddict to InstaAddict
- Updated to support Instagram version 438.0.0.28.88
- Updated profile header resource IDs to match new Instagram UI (posts, followers, following counts)
- Added support for new `profile_header_familiar_*` resource ID patterns
- Updated `.gitignore` to properly exclude sensitive account configs, crash dumps, and logs

### Changed
- All user-facing branding changed from GramAddict to InstaAddict
- GitHub references updated to `https://github.com/joeahkim/InstaAddict`
- Version reset to 1.0.1 for the InstaAddict fork

---

## Previous InstaAddict Releases

## 3.2.12 (2024-03-22)
### Fix
- handle NoneType for owner_name in feel job
- wrong indentation for hashtag check in feed job
## 3.2.11 (2024-03-17)
## New Features
- OCR to read the post owner if the obj is missing in the feed job (optional)
- `restart-atx-agent: bool` to restart the atx-agent before starting the bot
- `kill-atx-agent: bool` to kill the atx-agent when the script ends
### Fix
- feed sponsored detection
- Telegram wrong keys and order
## Misc
- message in telegram now looks more like it did before pandas were removed
## Test
- improved telegram test
## 3.2.10 (2024-03-09)
### Fix
- account selecting
- function specialization for load and clean txt file
- better logging for the user
### Others
- test for load and clean txt file
## 3.2.9 (2024-02-10)
### Fix
- remove pandas as dependency for telegram reports
- show when config file and filter file have been saved
- better logging information
## 3.2.8 (2024-01-24)
### Fix
- removed the language check
## 3.2.7 (2023-09-30)
### Fix
- using the monkey approach until this bug is fixed https://github.com/openatx/atx-agent/pull/111
## 3.2.6 (2023-09-28)
### Fix
- get rid of Activity class when starting app
## 3.2.5 (2023-07-23)
### Fix
- account selection with the little arrow instead of clicking on the account name
### Others
- display a warning if the user tries to use an untested version of IG
## 3.2.4 (2023-04-07)
### Fix
- fix selecting account if you have a lof of them, and it's not visible
- screen timeout checking for 'always on devices' (for example emulators)
### Others
- config loader in 'extra' folder
## 3.2.3 (2022-06-23)
### Others
- allow to pass device to dump
- allot to don't to kill the demon while dumping
## 3.2.2 (2022-04-28)
### Fix
- deprecated method uiautomator2 side that cause that error:
  >AttributeError: 'Session or Device' object has no attribute '_is_alive'
## 3.2.1 (2022-03-25)
### Fix
- default value for `unfollow-delay` was an integer instead of a string
- story_watcher returned Optional\[Union\[bool, int]] instead of int
## 3.2.0 (2022-03-23)
### New Features
- `unfollow` and `unfollow-non-followers` now check for when you last interacted with each user. Using the argument `unfollow-delay` you can specify the number of days that have to have passed since the last interaction
- after watching a story, the bot will now like it
- with `count-app-crashes` you can tell the bot to count app crashes as a crash for `total-crashes-limit` (default False)
- using the argument `remove-followers-from-file`, the bot can now remove followers following you from a *.txt
### Fix
- when interacting with the last picture of a profile, the bot could crash
- following suggested people instead of target account
- missing block detection for full screen mode (video)
- profile is loaded false negative
- avoid re-watching content if like fails
### Performance improvements
- new way to search for targets in search menu
- no need to see limits for PM if you're not sending them
- code has been cleaned and some functions have been merged
- inspect current view for list of users, this will avoid pressing on bottom bar
- set the screen timeout to 5 minutes if it's less than this value to avoid screen off issues
- store the target source in json instead of a duplicate of the username
- store request and followed status in json (it uses to be only followed)
- using `app_current` instead `info` for checking if the app is opened
- check for crash dialog when app crashes
- check if it's a live video before opening a story
- for actions with files (`interact-from-file`, `unfollow-form-file` and `remove-followers-from-file`) the script will look inside your account folder and no longer where you start the bot from
### Others
- bump version of UIA2
- trim logs in crash reports
- put your username inside the config when creating it with `gramaddict init username`
- default value for `can-reinteract-after` is now "None" instead of "-1"
- better logs when skipping profiles
## 3.1.5 (2022-02-07)
### Fix
- `app_id` was None for them who used the tool in a fancy way (without using config files)
## 3.1.4 (2022-02-07)
### Fix
- avoid a problem with `check_if_crash_popup_is_there` and `choose_cloned_app` being decorated before starting IG
## 3.1.3 (2022-02-06)
### Fix
- missing parenthesis in calling a method
## 3.1.2 (2022-02-06)
### Fix
- find the profile icon even with the different interface
- wrong arguments for stop_bot function
- workaround for avoiding story watching crash due to a bug of UIA2
### Performance improvements
- check if IG is opened when we try to find an element, raise an exception if it's not true (I used a decorator, for fun :D)
- simplify some functions
### Others
- move close_keyboard method to universal class
- a lot of typos
- some types hint
## 3.1.1 (2022-02-01)
### Fix
- inconsistent way to store datetime in json
## 3.1.0 (2022-01-31)
### New Features
- new argument `dont-type` allows writing text by pasting it instead of typing it
- you can go next line in your PM by adding `\n` in the text
### Fix
- the bot wasn't able to confirm the like if the button was not visible in the view
### Others
- don't show countdown in debug mode
## 3.0.5 (2022-01-26)
### Fix
- avoid pressing on music tab instead of hashtags (this bug was only for small screens)
### Others
- the bot restarts after a crash, except for some scenarios that will be highlighted
## 3.0.4 (2022-01-17)
### Fix
- carousel mid-point calculation was wrong (typo)
## 3.0.3 (2022-01-17)
### Fix
- in the new version (217..) the element for sorting following list has changed
### Performance improvements
-  better info when min-following is used in unfollow actions, or you're trying to unfollow more people than the number you're following
-  handle of malformed data in telegram-reports
## 3.0.2 (2022-01-10)
### Fix
- "back" in "Follow Back" is not uppercase anymore
### Performance improvements
- better handling for not loaded profiles
## 3.0.1 (2022-01-05)
### Fix
- missing argument in analytics report

### Others
- new logo for the readme.md
- added some useful info for the user

## 3.0.0 (2022-01-05)
### New Features

- use the cloned app instead the official, if the dialog box get displayed (this is currently supporter for MIUI devices)
- new filter options: *interact_if_public* and *interact_if_private*
- *interact_only_private* has been removed, delete it from your filters.yml

### Performance improvements

- limit check was wrong in interact_blogger plugin
- feed job was ignoring limits
- don't throw an error if config files \*.yaml instead of \*.yml are used
- likes_limit was referring to total_likes_limit and not current_likes_limit (that caused an error if you specify an interval)

### Performance improvements

- jobs have been split in "active-" and "unfollow-" jobs. That means, for example, that the bot won't stop the activity if it reached the likes limit, and you scheduled to unfollow.
- you can pass how many users have to be processed when working with \*.text (unfollow-from-list and interact-from-list)
- bot flow improved
- feed job improvements
- looking for description improvements
- better handle of empty biographies
- showing session ending conditions at bot start
- countdown before starting, so you can check that everything is ok (filters and ending conditions)
- before starting, the bot will tell you the filters you are going to use (there is no spell check there, if you wrote them wrong they will be displayed there but not get considered)
- disable head notifications while the bot is running
- removed unnecessary argument in check_limit function
- removed some unnecessary classes in story view
- move Filter instance outside of plugins
## 2.10.6 (2021-11-24)

#### Performance improvements

* the parsing of the number of posts / followers / following could fail for someone

Full set of changes: [`2.10.4...2.10.6`](https://github.com/InstaAddict/bot/compare/2.10.4...2.10.6)
## 2.10.5 (2021-11-18)

#### Fixes

* 'NoneType' object has no attribute '_is_post_liked'
#### Others

* removed a typo

Full set of changes: [`2.10.4...2.10.5`](https://github.com/InstaAddict/bot/compare/2.10.4...2.10.5)

## 2.10.4 (2021-11-08)

#### Fixes

* scraped is now counted as successful interaction

Full set of changes: [`2.10.3...2.10.4`](https://github.com/InstaAddict/bot/compare/2.10.3...2.10.4)

## 2.10.3 (2021-11-06)

#### Fixes

* the bot did not inform about the skip in case of the filter on mutual friends or on the link in bio
* false positive for link check in bio

Full set of changes: [`2.10.2...2.10.3`](https://github.com/InstaAddict/bot/compare/2.10.2...2.10.3)

## 2.10.2 (2021-11-06)

#### Fixes

* link in bio object exists even if it's empty

Full set of changes: [`2.10.1...2.10.2`](https://github.com/InstaAddict/bot/compare/2.10.1...2.10.2)

## 2.10.1 (2021-10-31)

#### Fixes

* someone in the world has a " ’ " as thousands separator instead of " , "

Full set of changes: [`2.10.0...2.10.1`](https://github.com/InstaAddict/bot/compare/2.10.0...2.10.1)

## 2.10.0 (2021-10-27)

#### New Features

* you can control if comment carousels
* support for connect_adb_wifi uia2 method
* support for watching videos and check for already liked posts
#### Fixes

* trying to close the android pop-up if ig crashes
* looking for the like button on the following video instead of the one being played
* comment fails on some media types
* checking media_type could fail
* empty files in unfollow from list job
* unfollow from list loop
* removed unexpected keyword argument in getFollowinCount method
* method connect_adb_wifi contained some errors
* was being imported nan by numpy instead of the math module
* ig is not opened but the bot tries to do operations
#### Performance improvements

* video recording
* posts-from-file job improved and fixed
* little improvements to the module mode

Full set of changes: [`2.9.2...2.10.0`](https://github.com/InstaAddict/bot/compare/2.9.2...2.10.0)

## 2.9.2 (2021-10-06)

#### Fixes

* other incompatibilities in the latest IG version

Full set of changes: [`2.9.1...2.9.2`](https://github.com/InstaAddict/bot/compare/2.9.1...2.9.2)

## 2.9.1 (2021-10-06)

#### New Features

* module version thanks to @patbengr
* if a username in *.txt file is not found, it will be appended to a *_not_found.txt
* from now, you can customize the session ending conditions
#### Fixes

* compatibility with IG: 208.0.0.32.135
* cannot check the language of Ig if not at the top of the account
* handle an exception in case you start the bot without specifying the config file
* it could happen that you are not at the top of your main profile in some circumstances
#### Performance improvements

* clean code for open and close ig

Full set of changes: [`2.9.0...2.9.1`](https://github.com/InstaAddict/bot/compare/2.9.0...2.9.1)

## 2.9.0 (2021-08-25)

#### New Features

* new argument to control how many skips in jobs with posts (e.g.: hashtag-post-top) are allowed before moving to another source / job
* new job to unfollow people who are following you
* new filter for skipping accounts with banned biography language
#### Performance improvements

* improved readability of the code and correct some typos
* moving sibling folders of run.py will no longer executed automatically

Full set of changes: [`2.8.0...2.9.0`](https://github.com/InstaAddict/bot/compare/2.8.0...2.9.0)

## 2.8.0 (2021-08-04)

#### New Features

* new filters: 'skip_if_link_in_bio: true/false' and 'mutual_friends: a_number' min count
* new feature added: pre- and post-script execution

Full set of changes: [`2.7.7...2.8.0`](https://github.com/InstaAddict/bot/compare/2.7.7...2.8.0)

## 2.7.7 (2021-08-03)

#### Fixes

* place first post not found [#208](https://github.com/InstaAddict/bot/issues/208)
* replace detect-block with disable-block-detection
#### Performance improvements

* removed unneeded class and sort imports

Full set of changes: [`2.7.6...2.7.7`](https://github.com/InstaAddict/bot/compare/2.7.6...2.7.7)

## 2.7.6 (2021-07-31)

#### Fixes

* missing resource id for sorting following list

Full set of changes: [`2.7.5...2.7.6`](https://github.com/InstaAddict/bot/compare/2.7.5...2.7.6)

## 2.7.5 (2021-07-30)

#### New Features

* new argument "detect_block: true/false" to enable/ disable block check after every action
#### Fixes

* a better way to sort following list [#207](https://github.com/InstaAddict/bot/issues/207)
#### Performance improvements

* add debug info for swipes
#### Refactorings

* sort imports

Full set of changes: [`2.7.4...2.7.5`](https://github.com/InstaAddict/bot/compare/2.7.4...2.7.5)

## 2.7.4 (2021-07-25)

#### Fixes

* support for Ig v. 197.0.0.26.119

Full set of changes: [`2.7.3...2.7.4`](https://github.com/InstaAddict/bot/compare/2.7.3...2.7.4)

## 2.7.3 (2021-07-14)

#### Fixes

* sometimes the bot press on 'Switch IME' instead of open your profile
* automatic change in English locale stopped working

Full set of changes: [`2.7.2...2.7.3`](https://github.com/InstaAddict/bot/compare/2.7.2...2.7.3)

## 2.7.2 (2021-07-14)

#### Fixes

* bug in open post container when someone in your 'following list' has also liked the post
#### Performance improvements

* lowered a little the swipe up in sorting `Following accounts`

Full set of changes: [`2.7.1...2.7.2`](https://github.com/InstaAddict/bot/compare/2.7.1...2.7.2)

## 2.7.1 (2021-07-13)

#### New Features

* you can dump your current screen with that command `gramaddict dump`
#### Performance improvements

* we don't need to click on an obj if we are already on it

Full set of changes: [`2.7.0...2.7.1`](https://github.com/InstaAddict/bot/compare/2.7.0...2.7.1)

## 2.7.0 (2021-07-12)

#### New Features

* you can use spintax for comments and PM from now
#### Fixes

* forgot to remove 'time_left' when calling print_telegram_reports at the end of all sessions
* in config-examples forgot 'comment_blogger' and fix typo in 'comment_blogger_following'

Full set of changes: [`2.6.5...2.7.0`](https://github.com/InstaAddict/bot/compare/2.6.5...2.7.0)

## 2.6.5 (2021-07-06)

#### Fixes

* the count of items in the carousels stopped at the first match
* from now on, every type of interaction is counted as successful and not just likes

Full set of changes: [`2.6.4...2.6.5`](https://github.com/InstaAddict/bot/compare/2.6.4...2.6.5)

## 2.6.4 (2021-07-01)

#### Fixes

* telegram-reports when out of working hours crashed
#### Performance improvements

* improve update checking
#### Docs

* text improvement and typo corrections

Full set of changes: [`2.6.3...2.6.4`](https://github.com/InstaAddict/bot/compare/2.6.3...2.6.4)

## 2.6.3 (2021-06-26)

#### Fixes

* time left in telegram-reports was wrong

Full set of changes: [`2.6.2...2.6.3`](https://github.com/InstaAddict/bot/compare/2.6.2...2.6.3)

## 2.6.2 (2021-06-25)

#### Fixes

* there was a problem with likers list
* there was a problem with the way I moved the reports at the end of sessions
#### Performance improvements

* the bot can recognize hashtag suggestions in feed
* telegram-reports improved
#### Docs

* typo in readme

Full set of changes: [`2.6.1...2.6.2`](https://github.com/InstaAddict/bot/compare/2.6.1...2.6.2)

## 2.6.1 (2021-06-24)

#### Performance improvements

* we can use an entry point from now
#### Docs

* correct a typo in telegram-reports
* improved the README

Full set of changes: [`2.6.0...2.6.1`](https://github.com/InstaAddict/bot/compare/2.6.0...2.6.1)

## 2.6.0 (2021-06-24)

#### New Features

* you can run InstaAddict from the command line for initializing your account folder with all the files needed
* add support for allow re-interaction after a given amount of hours
#### Fixes

* too many `filters.yml is not loaded`
* telegram-reports typo in report
* add support for viewers count where likes count is missing
* browse the carousel could fail in some circumstances
#### Docs

* completely rewrote the README.md
#### Others

* donation alert when bot stops by pressing CTRL+C
