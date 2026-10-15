<p align="center">
  <img src="https://github.com/ssucipto/instaaddict/raw/master/res/logo.png" alt="logo">
  <br />
  <h1 align="center">InstaAddict-AI — Enhanced Edition</h1>
  <br />
  <p align="center">Looking for production-grade Instagram automation? I'm proud to present <b>InstaAddict-AI (Enhanced Edition)</b>: a <b>100% free, open-source, human-like Instagram bot</b>. Grow your audience and engagement with automated liking, following, commenting, story watching, and autonomous posting on real Android devices or emulators. <b>No root required. No private APIs.</b></p>
  <p align="center">
    <a href="https://github.com/ssucipto/instaaddict/blob/master/LICENSE">
      <img src="https://img.shields.io/github/license/ssucipto/instaaddict?style=flat" alt="license"/>
    </a>
    <a href="https://github.com/ssucipto/instaaddict/releases">
      <img src="https://img.shields.io/badge/release-v1.4.4-blue?style=flat" alt="release"/>
    </a>
    <a href="https://www.python.org/">
      <img src="https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13-red.svg?style=flat" alt="Python"/>
    </a>
    <a href="https://github.com/ssucipto/instaaddict/pulls">
      <img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=flat" alt="PRs Welcome"/>
    </a>
    <a href="https://github.com/ssucipto/instaaddict/issues">
      <img src="https://img.shields.io/github/issues/ssucipto/instaaddict?style=flat" alt="Issues"/>
    </a>
    <a href="https://github.com/ssucipto/instaaddict/stargazers">
      <img src="https://img.shields.io/github/stars/ssucipto/instaaddict?style=flat" alt="Stars"/>
    </a>
    <a href="https://discord.gg/PvxsP8HFa">
      <img src="https://img.shields.io/badge/Discord-Join%20us-5865F2?style=flat&logo=discord&logoColor=white" alt="Discord"/>
    </a>
  </p>
</p>

<br />

## Table of Contents

* [📖 Complete User & Operator Guide](docs/USER_GUIDE.md) — Comprehensive guide covering Single-Account, Multi-Account Fleet, Vision AI, Telegram, and Troubleshooting
* [About This Project & Our Fork](#about-this-project--our-fork)
* [What's New in This Fork (InstaAddict-AI vs GramAddict)](#whats-new-in-this-fork-instaaddict-ai-vs-gramaddict)
  * [1. Full-Screen Reels & Modern IG (v446+) Compatibility](#1-full-screen-reels--modern-ig-v446-compatibility)
  * [2. Tiered Masterlist & Dynamic Hashtag Discovery Engine](#2-tiered-masterlist--dynamic-hashtag-discovery-engine)
  * [3. Persistent Non-Bot Followings Cache](#3-persistent-non-bot-followings-cache)
  * [4. Universal Ad Avoidance & In-App Browser Escape Watchdog](#4-universal-ad-avoidance--in-app-browser-escape-watchdog)
  * [5. Fluid 200ms ADB Native Swiping & Single-Swipe Flick Physics](#5-fluid-200ms-adb-native-swiping--single-swipe-flick-physics)
  * [6. Multimodal Gemini Vision AI Post Evaluation & Contextual Commenting](#6-multimodal-gemini-vision-ai-post-evaluation--contextual-commenting)
  * [7. Autonomous Content Queue & Post Uploader](#7-autonomous-content-queue--post-uploader)
  * [8. Two-Way Telegram Ingestion & Mobile Bot Control](#8-two-way-telegram-ingestion--mobile-bot-control)
  * [9. Modern Terminal User Interface (TUI) & Live Dashboard](#9-modern-terminal-user-interface-tui--live-dashboard)
  * [10. Multi-Account Fleet Orchestration & Emulator Management](#10-multi-account-fleet-orchestration--emulator-management)
  * [11. Production Telemetry & Self-Learning Dogfood Optimizer](#11-production-telemetry--self-learning-dogfood-optimizer)
* [Why Automate Your Instagram?](#why-automate-your-instagram)
* [Why InstaAddict-AI Over Other Bots?](#why-instaaddict-ai-over-other-bots)
* [How It Works](#how-it-works)
* [Compatibility & Known Working Versions](#compatibility--known-working-versions)
* [Features & Interaction Jobs](#features--interaction-jobs)
* [Quick Start Guide](#quick-start-guide)
  * [Single-Account Mode](#single-account-mode)
  * [Multi-Account Fleet Mode (Milestone 11)](#multi-account-fleet-mode-milestone-11)
* [Configuration & CLI Reference](#configuration--cli-reference)
* [Common Setup Issues & Troubleshooting](#common-setup-issues--troubleshooting)
* [Support This Project](#support-this-project)
* [Community](#community)

<br />

# About This Project & Lineage

**InstaAddict-AI (Enhanced Edition)** is an advanced fork and comprehensive architectural modernization maintained by [@ssucipto](https://github.com/ssucipto).

### Project Lineage & Credits
1. **InstaAddict-AI (Enhanced Edition)** — Maintained by [@ssucipto](https://github.com/ssucipto). Introduces modern IG v446+ Reels compatibility, multimodal Gemini Vision AI, tiered dynamic hashtag discovery, persistent non-bot caching, fluid 200ms ADB gestures, and in-app browser escape watchdogs.
2. **InstaAddict (Upstream Fork)** — Maintained by [@joeahkim](https://github.com/joeahkim), which first rebranded from GramAddict and introduced initial UI locator updates for IG 438+.
3. **GramAddict (Original Foundation)** — Originally created and architected by [mastrolube](https://github.com/mastrolube) and the open-source GramAddict community.

> This project is 100% free and open-source under the MIT License. All original architectural foundation credits go to the GramAddict and InstaAddict open-source contributors.

### Enhanced Edition Maintainer

<p>
  <a href="https://github.com/ssucipto">
    <img src="https://img.shields.io/badge/GitHub-ssucipto-181717?style=flat&logo=github" alt="GitHub"/>
  </a>
  <a href="https://github.com/ssucipto/instaaddict">
    <img src="https://img.shields.io/badge/Repository-ssucipto%2Finstaaddict-blue?style=flat&logo=git" alt="Repository"/>
  </a>
</p>

<br />

# What's New in This Fork (InstaAddict-AI vs GramAddict)

InstaAddict-AI introduces major architectural enhancements, new subsystems, and critical bug fixes that transform the bot into an autonomous, self-healing growth engine:

---

### 1. Full-Screen Reels & Modern IG (v446+) Compatibility
- **Modern Reels Viewer Support**: In Instagram v446+, opening video posts from hashtag grids launches the full-screen Reels viewer (`clips_viewer_view_pager`, `root_clips_layout`, `clips_viewer_container`). InstaAddict-AI natively handles this layout.
- **Multi-Tier Author Resolution**: Post author discovery now gracefully cascades across feed locators (`ROW_FEED_PHOTO_PROFILE_NAME`), Clips text locators (`CLIPS_AUTHOR_USERNAME`), regex content description extraction (`CLIPS_AUTHOR_PROFILE_PIC` via `"Profile picture of ([\w.]+)"`), and header components (`ROW_FEED_PROFILE_HEADER`, `CLIPS_AUTHOR_INFO_COMPONENT`).
- **Decoupled Ad Classification**: Fixed a longstanding bug where failing to click an author's header unconditionally returned `is_ad = True`. Missing author resolution now returns `(False, False, is_hashtag)`, completely eliminating false-positive ad skips on organic content.
- **Native Reels Like Button**: Automatically recognizes and interacts with `ResourceID.LIKE_BUTTON` (`com.instagram.android:id/like_button`).
- **Fast Caption Extraction**: Directly queries `CLIPS_CAPTION_COMPONENT` with immediate exit, preventing 8 futile 200px swipe-downs on captionless reels.

---

### 2. Tiered Masterlist & Dynamic Hashtag Discovery Engine
- **4-Tier Curated Masterlist**: Organizes hashtags into structured tiers (`accounts/<username>/hashtags.yml`):
  1. *Tier 1 (Local Community & Geo)*: High engagement local community tags.
  2. *Tier 2 (Breed & Niche)*: Core profile topic and breed tags.
  3. *Tier 3 (Lifestyle & Adventure)*: Contextual outdoor/lifestyle activity tags.
  4. *Tier 4 (Reach & Trending)*: High-volume reach tags.
- **Dual Expansion Strategies**:
  - *Strategy 1 (Gemini AI Expansion)*: Triggered via `--expand-hashtags`, leverages Google Gemini API to synthesize trending niche tags aligned with your account persona.
  - *Strategy 2 (In-App Caption Harvester)*: Silently scans post captions during live interaction loops with zero extra network or ADB overhead, logging observed tags in `discovered_hashtags.json`.
- **Deterministic Mathematical Governance Rules**:
  - `R-ADD-1` to `R-ADD-4`: Auto-promotes tags after 3+ sightings, filtered against a strict anti-spam blacklist and semantic relevance keywords, auto-classifying them into appropriate tiers.
  - `R-ROT-1` to `R-ROT-3`: Proportional tier sampling (2:2:1:1 balanced ratio), 2-session anti-fatigue cooldowns, and randomized sequence execution.
  - `R-PRN-1` to `R-PRN-2`: Automatically marks 0-result tags as `DEAD` and benches over-interacted tags for 7 days (`SATURATED`).

---

### 3. Persistent Non-Bot Followings Cache
- **Instant O(1) Memory Lookups**: Avoids repetitive UI element scraping and log spam by persisting known non-bot followings in `accounts/<username>/non_bot_followings.json`.
- **Atomic Disk Writes**: Uses `atomicwrites` to ensure atomic temporary file swaps, eliminating corruption on sudden process termination.
- **Fast-Skip Unfollow Engine**: Pre-seeds checked sets in `ActionUnfollowFollowers` for script-based unfollow modes, skipping organic accounts instantly.
- **Automatic Invalidation**: Automatically removes accounts from the cache whenever followed or unfollowed.
- **CLI Ergonomics**: Added `--clear-non-bot-cache` and `--ignore-non-bot-cache`.

---

### 4. Universal Ad Avoidance & In-App Browser Escape Watchdog
- **In-App Browser Escape**: Automatically detects and closes `BrowserLiteInMainProcessIGActivity` and external Chrome overlays via native close buttons (`ig_browser_close_button`), fallback back-presses, and foreground app relaunching.
- **Multi-Vector Ad Detection**: Combines sponsored badges, server components, and post-relative bounded CTA button coordinates to guarantee ads are never liked or scraped.
- **System Package Whitelisting**: Protects Android system UI (`com.android.systemui`, `android`, and IME keyboards) from false-positive dismissals.

---

### 5. Fluid 200ms ADB Native Swiping & Single-Swipe Flick Physics
- **Native ADB Swipes**: Completely replaced jerky `uiautomator2.drag` calls with calibrated native `adb shell input swipe` commands.
- **Single-Swipe Reels Scroll**: Executes a single fluid vertical flick (80% down to 20% display height) for full-screen Reels.
- **Removed Redundant Swipes**: Stripped the obsolete `HALF_PHOTO` swipe call from `handle_sources.py` and the 3-retry gap loop from `swipe_to_fit_posts`, eliminating 4-5 micro-jerks per post.
- **200ms Flick Velocity**: Calibrated duration to 200ms, creating a smooth and natural scroll that mirrors human finger motion.

---

### 6. Multimodal Gemini Vision AI Post Evaluation & Contextual Commenting
- **Gemini 2.5 Flash Multimodal Reasoning**: Analyzes post imagery and video frames to generate hyper-contextual comments matching your account persona (`accounts/<username>/ai-persona.yml`).
- **One-Shot Evaluate & Comment**: Combines relevance evaluation and comment generation into a single prompt, cutting API requests and latency by 50%.
- **512x512 LANCZOS Payload Compression**: Compresses screenshots before transmission to conserve bandwidth and API token limits.
- **Resilient Quota Handling**: Exponential backoff retry loops for 429 quota exhaustion and payload sanitizers for safety finish reasons.
- **Throttling**: Added `--evaluate-percentage` to control API usage per session.

---

### 7. Autonomous Content Queue & Post Uploader
- **Native Intent Architecture (`com.instagram.share.ADD_TO_FEED`)**: Bypasses fragile tab navigation, bottom navigation bars, and Android file pickers by pushing queued media directly to device storage, registering it with the Android MediaStore (`content://media/external/images/media/<id>`), and dispatching an explicit intent to Instagram's `ShareHandlerActivity`.
- **Dual Content Queue Paths**: Supports modern `accounts/<username>/content_queue/pending/` as well as legacy `upload_queue/` with case-insensitive media matching (`.jpg`, `.jpeg`, `.png`, `.mp4`).
- **Flexible Captioning & Sidecars**:
  - *Raw Text Sidecars*: Plain text `.txt` sidecars (e.g. `photo.txt`).
  - *Structured JSON Sidecars*: Rich metadata `.json` sidecars (e.g. `{"caption": "..."}`).
  - *Multimodal AI Fallback*: Uses Gemini Vision AI to automatically generate contextual captions when no sidecar file is present.
- **Configurable Rate Limiting**: Added `--upload-rate-limit-hours` (default: `12.0` hours, set to `0` to disable) to enforce safe cadences and prevent over-posting.
- **Interaction Limit Decoupling**: Uploads are decoupled from interaction quotas (likes/follows), ensuring scheduled content publishes reliably even when daily engagement targets have been met.
- **Modern IG v446+ Composer Automation**: Multi-step composer automation (Next buttons via `media_thumbnail_tray_button`, dismissal of modal dialogs, typing into `caption_input_text_view`, tapping `share_footer_button`, and verifying return to the Home feed).
- **Post-Upload Archiving**: Successfully published media and sidecars are automatically archived to `content_queue/published/`.

---

### 8. Two-Way Telegram Ingestion & Mobile Bot Control
- **Interactive Control Commands**: Full remote command and control directly from your phone via Telegram (`/status`, `/pause`, `/resume`, `/stop`, `/skip`, `/queue`, `/addphoto`, `/stats`, `/help`).
- **Direct Content Ingestion**: Send media (photos and videos) with captions directly to the Telegram bot; it validates, stages, and enqueues items into `accounts/<username>/content_queue/pending/` with accompanying sidecars.
- **Real-Time Event Alerts**: Immediate push notifications for soft-blocks, CAPTCHAs, successful post uploads, and session milestones.
- **Access Control Whitelist**: Strict `chat_id` filtering ensures only authorized operator Telegram IDs can query or dispatch commands.

---

### 9. Modern Terminal User Interface (TUI) & Live Dashboard
- **Real-Time Curses/Rich Dashboard**: Full live terminal visualization showing all active accounts, current actions, running timers, likes/follows/comments quotas, and emulator health in real time.
- **Headless & Plain Mode**: Automatically falls back or disables TUI via `--no-tui` for background daemons, cron jobs, and CI/CD pipelines.
- **Keyboard Shortcuts**: Quick hotkeys (`q` to quit, `p` to pause/resume accounts, `tab` to cycle views).

---

### 10. Multi-Account Fleet Orchestration & Emulator Management
- **Concurrent Multi-Process Supervisor**: Run multiple accounts across multiple emulators simultaneously with zero crosstalk (`python run.py multi`).
- **IPC Status Beaconing**: Atomic JSON state beaconing (`.ipc/accounts/<username>.json`) enables external dashboards and CLI queries (`python run.py multi --status`) with zero lock contention.
- **Cold Boot & Emulator Health Watchdog**: Automatically detects frozen emulators, dead ADB connections, or crashed instances, and triggers clean headless reboots and app relaunches.
- **Dynamic Hot-Reloading**: Modify schedules, limits, or account pools in `multi_config.yml` and hot-reload active workers (`python run.py multi --reload`) without stopping running tasks.
- **Graceful Signal Management**: Send clean termination signals (`python run.py multi --stop [user]`) to allow in-flight post interactions to finish cleanly before process teardown.

---

### 11. Production Telemetry & Self-Learning Dogfood Optimizer
- **Unhandled Crash Interception**: Installed a global `sys.excepthook` interceptor that logs fatal Python exceptions and third-party stack traces into `_error_trace.log` before exit.
- **Windows File Lock Safety**: Explicitly closes file handlers before unlinking, eliminating `PermissionError: [WinError 32]` collisions on Windows.
- **Continuous Markdown History**: Automatically appends run logs to `accounts/<username>/history.md` (never overwritten) and generates timestamped markdown session reports in `accounts/<username>/reports/`.
- **Dogfood Self-Learning Optimizer (`dogfood.py`)**: Analyzes session outcomes, conversion yields, and error patterns to produce automated parameter tuning recommendations in `tuning_suggestions.md`.
- **Task Sequence Randomizer**: Shuffles active interaction jobs every session (`--randomize-tasks`), preventing predictable algorithmic patterns that Instagram detects.
- **Android 14+ UIAutomator2 & FastInputIME**: Patched regex dumpsys parsing and native `Mode.PASTE` direct text injection to prevent keyboard stutter and timeouts on modern Android versions.

<br />

# Why Automate Your Instagram?

Organic discovery on Instagram heavily favors accounts that already receive massive engagement. If you are starting fresh or growing a niche profile, your posts rarely appear in explore or hashtag feeds unless people interact with your profile first.

InstaAddict-AI automates the repetitive, time-consuming interaction work (liking targeted posts, following niche-relevant users, watching stories, and commenting) so real people are notified, check out your profile, and follow you back organically.

## Does this replace quality content?
**No.** Automation gets your profile discovered; your content determines whether they stay and follow. Pair InstaAddict-AI with engaging posts, high-quality visuals, and a clear bio.

## Will I get banned?
InstaAddict-AI avoids private API calls, making it vastly safer than cloud-based API bots. However, **Instagram enforces behavioral velocity limits**. If a bot (or human) follows 500 accounts in an hour, it will trigger soft-blocks. We strongly advise using modest, randomized session limits that mimic human routines.

<br />

# How It Works

Unlike competing tools that send unauthorized HTTP requests directly to Instagram's private backend, InstaAddict-AI controls the official Android Instagram app installed on your physical device or emulator using **Android Debug Bridge (ADB)** and **UIAutomator2**.

```
┌─────────────────────────────────────────────────────────────┐
│                       InstaAddict-AI                        │
│  (ConfigArgParse, HashtagManager, Gemini AI, DogfoodEngine) │
└──────────────────────────────┬──────────────────────────────┘
                               │
                      [ADB & UIAutomator2]
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 Android Device / Emulator                   │
│   (Official Instagram App v446+ | Android 7.0 - 14.0+)      │
│   - Simulates human touches, 200ms flick gestures, typing   │
│   - Decoupled ad detection & in-app browser escape watchdog │
└─────────────────────────────────────────────────────────────┘
```

Your device physically renders the UI, scrolls feeds, inspects elements, and taps buttons exactly as a real person would.

<br />

# Compatibility & Known Working Versions

| Component | Tested & Verified | Notes |
| :--- | :--- | :--- |
| **Instagram APK** | **440.0.0.46.86 – 446.0.0.0.0+** | Full compatibility with both classic feed and modern full-screen Reels viewer |
| **Python** | **3.11 – 3.13** | Tested on Python 3.11.x, 3.12.x, and 3.13.x |
| **UIAutomator2** | **2.16.14 – 2.16.26** | Patched for Android 14+ FastInputIME |
| **Operating Systems** | Windows 10/11, macOS (Intel & Apple Silicon), Linux, Termux (Android) | Full cross-platform support |
| **Emulators** | MEmu, LDPlayer, Android Studio AVD (ARM64) | ARM translation or ARM64 system images required |

<br />

# Features & Interaction Jobs

### Interaction Sources
- **Hashtag Posts Top & Recent**: Likes, comments, and follows users posting under targeted hashtags. (Supports modern full-screen Reels).
- **Hashtag Likers Top & Recent**: Interacts with active users who liked posts in targeted hashtags.
- **Blogger Followers & Following**: Interacts with audiences of competing or complementary accounts.
- **Blogger Post Likers**: Interacts with users actively liking a specific blogger's latest posts.
- **Place Posts & Likers Top & Recent**: Geo-targeted interactions based on locations.
- **Feed Interaction**: Naturally likes and comments on posts in your own home feed.
- **Lists from Text Files**: Interacts with usernames or post URLs loaded from `.txt` files.

### Unfollow & Hygiene Jobs
- `unfollow`: Unfollows users followed by the bot after a grace period.
- `unfollow-non-followers`: Unfollows users who did not follow back.
- `unfollow-any`: Unfollows users regardless of who followed them.
- *Persistent Non-Bot Cache*: Automatically fast-skips organic followings without redundant element checks.

### Autonomous Capabilities
- **Multimodal AI Comments**: Contextual comments generated by Gemini Vision.
- **Story Watching**: Watches stories while interacting with profiles.
- **Carousel Browsing**: Swipes through multi-image carousel posts.
- **Video Watching**: Watches videos and reels for realistic, randomized durations.
- **Content Upload Pipeline**: Automatically publishes scheduled posts from `upload_queue/`.

<br />

# Quick Start Guide

### Prerequisites
1. **Python 3.11+ / 3.13**: Make sure Python is added to your system `PATH`.
2. **Android Debug Bridge (ADB)**: Included with Android SDK platform-tools.
3. **Android Device or Emulator**: USB debugging enabled.

---

### Step 1: Clone and Set Up Virtual Environment

```bash
# Clone the repository
git clone https://github.com/ssucipto/instaaddict.git
cd instaaddict

# Create a virtual environment
python -m venv .venv

# Activate virtual environment:
# Linux/macOS:
source .venv/bin/activate
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Windows (CMD):
.venv\Scripts\activate.bat

# Install dependencies
pip install -r requirements.txt
```

---

### Step 2: Set Up Device via ADB

1. Connect your Android phone via USB and enable **USB Debugging** in Developer Options (or launch your emulator).
2. Verify ADB connection:
   ```bash
   adb devices
   ```
   *Output should display your device ID:*
   ```text
   List of devices attached
   emulator-5554    device
   ```
3. Initialize UIAutomator2 on your device:
   ```bash
   python -m uiautomator2 init
   ```

---

### Step 3: Configure Your Account

Run the bot with your target Instagram username. On first run, it will automatically scaffold a configuration directory under `accounts/<username>/`:

```bash
python run.py --config accounts/my_instagram_user/config.yml
```

Edit `accounts/my_instagram_user/config.yml` to specify your targeted hashtags, bloggers, and safe interaction limits.

---

### Step 4: Run the Bot

#### Single-Account Mode
Run the bot against a single account configuration:

```bash
# Run with standard configuration
python run.py --config accounts/my_instagram_user/config.yml

# Run with task sequence randomizer
python run.py --config accounts/my_instagram_user/config.yml --randomize-tasks

# Run hashtag interaction with dynamic AI expansion
python run.py --config accounts/my_instagram_user/config.yml --expand-hashtags
```

#### Multi-Account Fleet Mode (Milestone 11)
Orchestrate a concurrent fleet of accounts across multiple emulators simultaneously with live TUI monitoring, automated health watchdogs, and IPC beaconing:

```bash
# Launch the fleet supervisor with interactive TUI dashboard
python run.py multi

# Launch in headless/plain logging mode (for servers/cron/CI)
python run.py multi --no-tui

# Run only specific accounts from the fleet
python run.py multi --only dog_fanpage cat_lovers

# Query active fleet status and live counters from IPC beacons
python run.py multi --status

# Hot-reload configuration without stopping active workers
python run.py multi --reload

# Gracefully stop a specific account or the entire fleet
python run.py multi --stop dog_fanpage
python run.py multi --stop
```

> 📖 **Need more detailed walkthroughs?** See the [Complete User & Operator Guide](docs/USER_GUIDE.md) for deep-dive tutorials on Telegram pairing, Vision AI prompting, multi-emulator setup, and safety configurations.

<br />

# Configuration & CLI Reference

InstaAddict-AI features rich command-line flags and configuration files:

### Multi-Account Fleet Commands (`python run.py multi`)

| Command / Flag | Description |
| :--- | :--- |
| `python run.py multi` | Launches the multi-account supervisor with rich TUI dashboard. |
| `--status` | Queries active IPC state beacons and outputs an instantaneous tabular status summary without starting workers. |
| `--only <acc1> [acc2...]` | Filters the fleet to run only the specified accounts. |
| `--reload` | Signals active supervisor to hot-reload `multi_config.yml` schedules and limits. |
| `--stop [username]` | Sends a graceful stop signal to a specific account worker or all running workers. |
| `--no-tui` | Forces standard linear terminal logging, disabling the interactive curses dashboard. |
| `--config <path>` | Custom path to the fleet configuration file (default: `multi_config.yml`). |

### Single-Account Command-Line Flags (`python run.py`)

| Flag | Description |
| :--- | :--- |
| `--randomize-tasks` | Shuffles the active job sequence randomly on every session for humanized behavior. |
| `--expand-hashtags` | Triggers Gemini AI expansion to discover and synthesize new niche tags at session start. |
| `--no-harvest-hashtags` | Disables silent background caption hashtag harvesting. |
| `--hashtags-file <path>` | Custom path to the tiered `hashtags.yml` masterlist file. |
| `--clear-non-bot-cache` | Clears the persistent `non_bot_followings.json` cache before starting. |
| `--ignore-non-bot-cache`| Bypasses the non-bot cache during unfollow operations. |
| `--evaluate-percentage <0-100>` | Percentage of posts to evaluate with Gemini Vision AI. |
| `--upload-posts` | Enables the autonomous post uploader plugin. |
| `--upload-rate-limit-hours <float>` | Minimum hours between post uploads (default: 12.0, 0 to disable). |
| `--upload-queue-dir <path>` | Custom path to the upload media queue directory. |

### Configuration Files Overview

```
instaaddict/
├── multi_config.yml         # Fleet orchestration: accounts, emulators, schedules, concurrency
├── .ipc/                     # Transient IPC beacons and control signals
│   ├── accounts/             # Atomic per-account state beacons (.json)
│   └── signals/              # Hot-reload and stop signal triggers (.stop, .reload)
└── accounts/<your_username>/
    ├── config.yml            # Main configuration: limits, jobs, working hours, speeds
    ├── filters.yml           # Demographic filters: business, private, follower ranges
    ├── hashtags.yml          # Tiered masterlist: Local, Breed, Lifestyle, Reach pools
    ├── ai-persona.yml        # Character prompt definition for Gemini Vision AI commenting
    ├── non_bot_followings.json   # Persistent cache of verified non-bot accounts (atomic writes)
    ├── discovered_hashtags.json  # Harvested caption hashtag frequency counts
    ├── history.md            # Continuous, non-overwritten markdown run history
    ├── reports/              # Timestamped per-session analytics markdown reports
    ├── content_queue/        # Autonomous post queue (pending/ and published/ archives)
    └── upload_queue/         # Legacy upload directory (backwards-compatible)
```

<br />

# Common Setup Issues & Troubleshooting

### 1. `Can't find the owner name, skip.` or Posts Skipped as Ads
- **Resolution**: Update to InstaAddict-AI v1.3.0+. Modern full-screen Reels viewer locators (`CLIPS_AUTHOR_USERNAME`, `CLIPS_AUTHOR_PROFILE_PIC`) are natively handled, and missing owner lookup is decoupled from ad detection.

### 2. Jerky Scrolling or Multiple Swipes Per Post
- **Resolution**: InstaAddict-AI v1.3.0 uses calibrated 200ms native ADB swipe gestures and single-swipe Reels navigation. Ensure `speed-multiplier: 1` in `config.yml`.

### 3. Stuck in In-App Browser Ad Overlay
- **Resolution**: InstaAddict-AI includes an automated browser escape watchdog (`escape_in_app_browser`) that detects `BrowserLiteInMainProcessIGActivity` and dismisses ad overlays automatically.

### 4. `ModuleNotFoundError: No module named 'pkg_resources'`
```bash
pip install standard-pkg-resources
```

### 5. `adb` Command Not Found (Windows)
Ensure platform-tools is added to your Environment `PATH` variable, and restart PowerShell / terminal.

<br />

# Support This Project

InstaAddict-AI (Enhanced Edition) is 100% free and open-source. Maintaining compatibility against Instagram's rapid UI shifts requires continuous research and testing. If this bot has helped your workflow or account growth, please consider giving it a ⭐ on GitHub and sharing it with the community!

<br />

# Community

* 💬 **Discord**: [Join the Discord community](https://discord.gg/PvxsP8HFa) for community support, setup assistance, and growth discussions.
* 🐛 **Issue Tracker**: Found a bug or broken locator on a new Instagram release? [Submit an Issue](https://github.com/ssucipto/instaaddict/issues).
* 🛠️ **Contributing**: Pull requests, bug reports, and locator updates are welcome!

---

**Disclaimer**: This project is for educational and personal automation purposes. Always use conservative interaction limits to avoid triggering Instagram velocity flags.
