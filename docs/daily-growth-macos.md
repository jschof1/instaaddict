# Short daily sessions on macOS

`scripts/daily_growth.py` runs one automatic reviewed batch per Europe/London calendar day.
Use the existing Python environment, logged-in account and headless Android launcher.
All settings and evidence stay in the ignored `accounts/<username>/growth` directory.

The worker permits at most ten follows and twenty likes per day. Earlier manual bot
sessions and conservatively reserved manual batches count toward those limits. It processes at most ten fresh profiles,
with at most two likes each. The bot's comments, private messages, unfollows and
publishing remain disabled. A separate optional helper can post at most two
prepared public comments as `uk.tradeleads` per UK day. These limits bound the session; they do not guarantee account safety
or follower growth. Instagram restrictions stop the worker for review.

Relevant videos encountered in the reviewed profile batch use 15–30 second viewing
windows, bounded by the existing session deadline and any remaining video time.
Saved sessions expose `video_watch_windows` and `video_watch_seconds` separately
from story watches, likes and comments. These measure completed viewing waits;
they are not Instagram-confirmed views or evidence that playback continued throughout.
No extra discovery job or unlimited scrolling is enabled.
An explicit failed-like confirmation stops the daily worker for review rather than
allowing it to continue following more profiles with no confirmed likes.

## Private setup

Create `settings.json` containing:

```json
{"dailyFollows": 10, "dailyLikes": 20, "timezone": "Europe/London"}
```

`queue.json` contains `preparedAt` and `targets`. Each target needs `handle`,
`sourceUrl`, `instagramUrl`, `trade`, `serviceArea` and `evidence`. The source must
be the business's own site or business listing explicitly linking its Instagram
account. Use lowercase handles without `@`, and canonical Instagram URLs starting
`https://www.instagram.com/`. Review relevance before adding targets. Queue data
is not committed. Previously interacted or attempted profiles are never replayed
automatically. Refill this finite queue when the status shows it is empty.

The existing `~/Applications/InstaAddict/Start Android.command` must start the
configured AVD on port 5554 in the foreground. The worker starts it only when
`emulator-5554` is absent and shuts down only that owned session. It does not
take over an already open emulator. Keep the original account filters with
comment/PM permissions disabled.

### Optional finite public comment queue

There is no AI generation, discovery or generic fallback. The parent prepares each
comment from live profile and caption proof. `sourceUrl` must be the matching
Instagram profile; retain any business website research separately. Only
`uk.tradeleads` is supported. Private messages stay at zero. The scoped public
comment permission does not add a per-draft approval step.

Absent `comment-policy.json` means off. To enable it, create these private files
in `growth` (mode 600), including an initially empty ledger if there is no history:

`comment-policy.json`:

```json
{"enabled":true,"dailyLimit":2,"timezone":"Europe/London"}
```

`comment-queue.json`:

```json
{"comments":[{"id":"roof-20261019-1","handle":"example.roofing","postUrl":"https://www.instagram.com/p/CODE/","captionSnippet":"Exact excerpt from this post","text":"Prepared post-specific comment.","sourceUrl":"https://www.instagram.com/example.roofing/","expiresAt":"2026-10-26T17:00:00+00:00"}]}
```

`comment-ledger.json`:

```json
{"version":1,"intents":[]}
```

Queue fields are required. IDs use letters, digits, hyphens or underscores. URLs
must be exact HTTPS `instagram.com` or `www.instagram.com` post URLs, either
`/p/CODE/` or `/handle/p/CODE/`, without query strings or fragments. Any URL handle
must match `handle`. Caption excerpts and comments must be nonempty and at most
220 characters. Reject links and sales pitches; validation includes a conservative
content filter, while relevance and wording come from the prepared source proof.
Use timezone-aware ISO timestamps and normally a seven-day expiry. Expired entries
are skipped; malformed entries stop the run even if expired. Refill the finite
queue as needed. Status reports enabled, daily charged, remaining and pending
(unexpired, unconsumed) counts.

Each ledger intent copies all seven queue fields and adds `day` (UK date),
`reservedAt` (aware ISO timestamp) and `state`. Optional fields are `finishedAt`,
`evidence` (private XML path), and `receiptSessionId` when the same confirmed
comment is already counted in a bot session. Import earlier manual comments as
`posted` intents with their actual timestamps before enabling the helper. For example:

```json
{"version":1,"intents":[{"id":"manual-20261019-1","handle":"example.roofing","postUrl":"https://www.instagram.com/p/CODE/","captionSnippet":"Exact excerpt from this post","text":"Exact full comment already posted.","sourceUrl":"https://www.instagram.com/example.roofing/","expiresAt":"2026-10-26T17:00:00+00:00","day":"2026-10-19","reservedAt":"2026-10-19T12:00:00+01:00","state":"posted"}]}
```

The helper validates the account, post and composer before reserving an attempt.
A failure during those checks leaves the ledger untouched and records the exact
reason in the worker journal. After validation it checks that the draft is still
eligible, then saves `reserved` with an atomic replacement and syncs both the
file and directory before typing. The terminal states for that attempt are
`posted` or `alreadyPosted`. Power loss can leave `reserved`; recovery changes it to
`uncertain`. Every state charges the reservation's UK day. Historical bot
`total_comments` also charge that day; `receiptSessionId` avoids counting the
same confirmed receipt twice. Unknown/manual actions outside these records must
be reconciled into the ledger. Never reset the ledger to regain budget.

An attempted post shortcode OR normalized full comment text is permanently
consumed across days. An uncertain intent is never retried. A safety fault or
unresolved reservation blocks further actions until reviewed. Any failure after
the durable reservation still consumes its intent and requires review.

For the observed empty-composer failure, `scripts/review_comment_not_sent.py`
provides an explicit operator-only reconciliation. It requires exact original
source, log and composer XML hashes; rechecks owner, caption, timing, absence of
typing/receipt phases and the pre-typing failure path; and takes both worker and
comment locks. Use `--help` for required evidence arguments and `--dry-run` first.
Only a proved pre-typing `uncertain` intent can become `reviewedNotSent`, with a
separate `notSentReview` record. Its original charge and permanent post/text/id
consumption remain. This does not count a comment or archive the safety fault.
Post-submit or unproved outcomes stay uncertain and held. Older code fails closed
on the new state, so deploy the checked revision before applying reconciliation.

For each intent the helper verifies the logged-in account, exact post owner and
caption excerpt, empty known composer and absence of reply context or restrictions.
It verifies the exact typed text, clicks Post once and requires a single XML node
whose complete description is `uk.tradeleads said FULLCOMMENT`. It then reopens
the exact post, revalidates owner/caption and saves a fresh full receipt. Missing
or ambiguous confirmation stays uncertain. An already visible exact comment is
charged as `alreadyPosted` without typing. XML evidence is private in
`growth/comments-log` (folder 700, files 600).

The bot's saved job must be new, match this config, finish successfully with
zero recoveries/crashes and zero unexpected actions before comments can start.
The helper runs under `.venv/bin/python` in the same owned emulator session.
When the follow queue is empty or its budget used, eligible prepared comments
can run alone. There is no additional schedule. A started day still prevents
another same-day run.

For read-only selector checks, import `scripts/public_comments.py`, import
`InstaAddict.core.device_facade` before connecting uiautomator2, then use
`CommentUI(device, growth_path).open_and_validate(entry)`. This path only opens
the account/post/composer and saves XML: it does not type, submit or change the
ledger. It dismisses an observed previous comments sheet with one Back, and uses
one further Back only for an observed post detail without the profile tab.

```sh
.venv/bin/python scripts/daily_growth.py status --account uk.tradeleads
.venv/bin/python scripts/daily_growth.py run --account uk.tradeleads
.venv/bin/python scripts/daily_growth.py pause --account uk.tradeleads
.venv/bin/python scripts/daily_growth.py resume --account uk.tradeleads
```

## Schedule and operating limits

Use a per-user LaunchAgent with `StartCalendarInterval` hour 10, minute 0, with
the Mac's time zone set to Europe/London. Set absolute Python/script paths,
`WorkingDirectory` to the checkout, `RunAtLoad` false and `KeepAlive` false.
Enable the schedule only after a complete supervised session succeeds.

Since 23 November 2026 the worker runs on the MacBook Pro, not the Mac mini (the mini's
LaunchAgent is renamed `*.moved-to-macbook-20261123`). The LaunchAgent runs the worker
through `mac-resource-guard run --light --wait 60`; a refusal skips that day without
starting it. The launcher uses hardware graphics (`-gpu host`, 3 GB, 4 cores); software
rendering on the mini made Instagram take minutes to open and tripped the watchdog.

The MacBook runtime checkout is `~/GitHub/instaaddict`. The old
`~/Documents/GitHub/instaaddict` path is a symlink to that same checkout, including
the single account directory. Use the runtime path for the LaunchAgent's arguments,
working directory and log paths. On 24 November the Documents-based configuration
failed before Python started: launchd reported `Operation not permitted` and exit 78.
A shell check of the worker alone does not detect that background access failure.
Validate a changed installation through a separate, temporary LaunchAgent with
the same executable, environment and working directory, replacing the worker's
`run` subcommand with `status`. Remove the temporary service after its exit and
inspect its output. Keep `RunAtLoad` and `KeepAlive` false on the real daily agent;
reloading it must not start an extra batch.

`~/Library/Android/sdk` links to `~/.android-sdk-build`. The copied device only trusts the
mini's adb key, so `ADB_VENDOR_KEYS=~/.android/instaaddict-adbkey` must be set for the
launcher, the worker and any adb server that talks to it.
The SDK's `system-images` directory now lives on the mounted `/Volumes/LLM` volume;
verify that route before relying on the schedule. Never create an empty replacement
directory when the external volume is absent.

The `Growth status.command`, `Pause daily growth.command` and
`Resume daily growth.command` controls in `~/Applications/InstaAddict` operate on
this MacBook's runtime checkout. Status also prints the live launchd state and last
exit code. Old SSH controls targeting the mini do not control the current worker.
Public comments require a finite queue of individually checked posts and specific,
non-promotional wording. The account owner requested two such comments daily on
24 November. Replenish that queue from real post context; never reuse expired
entries or repeat historical comments. DMs, publishing and unfollows stay disabled.

The Mac must remain powered and its user logged in. A sleeping Mac runs
the missed calendar job when it wakes; a powered-off Mac cannot run it. The
worker prevents sleep only during a session.

Starting Android requires 8 GiB free; a run stops below a 3 GiB reserve. Boot
has four minutes and the bot twenty minutes. The comment helper has at most
180 seconds, sharing the overall 24-minute ceiling. Pause, UK day rollover,
emulator loss, log size and the disk reserve are monitored during comments too.
Overlapping workers, another bot, an occupied emulator, duplicate days and
unreviewed faults prevent new actions. A started day is never retried
automatically, even when it performed no actions.

`state.json` and `days/YYYY-MM-DD.json` retain results; `logs` retains diagnostics.
Bot-recorded likes/follows are outgoing actions, not proof of new followers or
leads. A clean exit must also have a saved, completed job without crashes or
watchdog recoveries before the worker reports success.
The reserved like budget is a conservative charge, not a count of confirmed likes.
Use `botRecordedActions`, the matching finished saved session, and its log to
report actual actions. A loaded schedule, an old completed journal, a skipped day,
and a successful read-only launch probe are not a new completed Instagram run.

Opened-post and video hearts can expose `content-desc="Liked"` while
`selected=false`. Their state checks use the exact heart labels `Like`, `Liked`
and `Unlike`. A missing control or unfamiliar label is unknown: it cannot confirm
a like, authorize an initial toggle or authorize a fallback heart click. Offline
regression checks establish this selector contract; they do not establish the
outcome of earlier failed attempts or validate a live engagement run.

Older runs reserved before validating the composer. When an older reservation
has evidence of a pre-typing failure, use the explicit review described above.
Unresolved intent states and the separate worker fault each require review.

Pause stops an active bot and its owned emulator. Resume removes only a manual
pause; it cannot clear `fault.json`. Investigate the saved log, reconcile any
uncertain actions and repair the cause before manually archiving a safety fault.
An unfinished journal after a power loss also requires review. Keep the original
journal and action accounting. A repaired worker can resume on a future UK day
after the fault is reviewed. Recorded `Followed @...` transitions
are charged even if interruption preceded the bot's per-profile counter update.

## Daily operation and maintenance

The owner requested daily operation, including weekends, on 24 November. The
current caps are 10 follows, 20 likes and 2 prepared public comments. These are
maximums, not guaranteed totals. The live settings may retain lower caps during a
review; invalid or above-maximum settings fail closed. Every journal snapshots the
configured daily caps independently of the remaining budget. A started day keeps
its original action records and reservations when future caps change.

The daily 11:30 Europe/London maintenance check reads the actual process, scheduler,
day journal, log and saved session. It distinguishes success, skips, interrupted
runs and missing journals. It also owns source-verified prospect replenishment and
preparation of two unique, contextual public comments for the next run. A finite
queue is not an indefinite supply. No generic praise queue, promotional pitches or
automatic retries are permitted.

The dedicated device updated Instagram through Google Play during the 24 November
supervised batch. Android's exit record reported PACKAGE UPDATED, not a crash.
Instagram's per-app Play Store auto-update checkbox was switched off and read back
as unchecked. Review future Instagram upgrades deliberately before running the
bot; keep normal restriction, crash and foreground-loss stops enabled.
