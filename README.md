# DTZ TRIO Matchmaking Bot

A Telegram bot for DTZ TRIO members: gated by an access code you post in the
WhatsApp group, text-only profiles (no photos required), browse-and-like
matching, and admin moderation tools.

## How the WhatsApp → Telegram link works

Telegram and WhatsApp can't be technically connected — there's no API that
lets a Telegram bot check WhatsApp group membership. Instead:

1. An admin runs `/gencode` in the bot's Telegram chat.
2. The bot replies with a one-time code.
3. Post that code in the DTZ TRIO WhatsApp group.
4. Members DM the Telegram bot, send `/start`, and enter the code.
5. Each code works once — generate a new one whenever you want to open
   registration again (e.g., start of semester).

## Setup

1. **Create the bot**: message [@BotFather](https://t.me/BotFather) on
   Telegram, run `/newbot`, follow the prompts, copy the token it gives you.

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Set environment variables**:
   ```bash
   export BOT_TOKEN="123456:ABC-your-token-here"
   export ADMIN_IDS="111111111,222222222"   # your + co-founders' Telegram user IDs
   ```
   To find a Telegram user ID, have that person message
   [@userinfobot](https://t.me/userinfobot).

4. **Run it**:
   ```bash
   python bot.py
   ```

   For 24/7 uptime, deploy it on a small always-on host (e.g., a Railway,
   Render, or a VPS) and run it as a background service (systemd, pm2, or
   `screen`/`tmux`), since `run_polling()` needs a process that stays alive.

## Commands (members)

| Command | What it does |
|---|---|
| `/start` | Enter your access code, begin setup |
| `/menu` | Open the main menu — tap-friendly buttons for everything below |
| `/profile` | Create or redo your profile (gender, bio, what you're looking for, 3 icebreakers) |
| `/browse` | See the next profile matching your preference |
| `/matches` | List your mutual matches |
| `/sharephoto` | Share a photo with a match — only sent after they explicitly consent |
| `/anonymous` | Send an anonymous message to admins (Anonymous Night) |
| `/friendquestion` | Get randomly paired with another member + shared icebreaker questions |
| `/leavequeue` | Leave the Friendship Questions waiting queue |
| `/smashpass` | Vote Smash or Pass on fun, anonymized prompts (not real member photos) |
| `/leaderboard` | See the points leaderboard and your streak |
| `/help` | Full command list, shown with the menu buttons |
| `/report` | Report abusive behavior to admins |
| `/stop` | Opt out — deletes all your data from the bot |

## Commands (admins — set via `ADMIN_IDS`)

| Command | What it does |
|---|---|
| `/gencode` | Generate a one-time WhatsApp-group access code |
| `/ban <telegram_id>` | Ban a user from the bot |
| `/unban <telegram_id>` | Lift a ban |
| `/reports` | List open (unresolved) reports |
| `/stats` | Quick usage stats |
| `/nightopen` | Open Anonymous Night submissions |
| `/nightclose` | Close Anonymous Night submissions (e.g., if it's being misused) |
| `/broadcast <message>` | Message every verified, non-banned member right now, once |
| `/setreminder HH:MM <message>` | Set and enable the automatic daily nudge (24-hour, server local time) |
| `/reminderon` | Turn the daily automatic reminder on |
| `/reminderoff` | Turn the daily automatic reminder off |
| `/remindernow` | Send today's reminder immediately, without waiting for its scheduled time |

## Moderation flow

1. A member DMs the bot's target `@username` + reason via `/report`.
2. All admins get pinged instantly with the report and a ready-to-use
   `/ban <id>` command.
3. Admin reviews and runs `/ban` if warranted — this is enforced entirely
   within your own bot, which is the only account-banning your team
   actually controls (there's no way to ban someone's real WhatsApp or
   Telegram account from outside — only Telegram/Meta's own trust & safety
   teams can do that).

## Data & privacy notes

- Profiles are text-only by design — no photos are collected or required at
  signup or during browsing.
- Nobody is matched unless they register through the bot themselves
  (access code → `/start` → profile setup). There's no way to add someone
  to the pool on their behalf.
- Photos are only ever exchanged post-match, and only after the receiving
  party taps "Yes, show me" on an explicit consent prompt (`/sharephoto`).
  Declining sends no photo and notifies the sender it was declined.
- `/stop` fully deletes a user's row, likes, and matches.
- The database is a single SQLite file (`dtztrio.db`) — back it up
  periodically if you care about match history.
- Consider adding a short in-bot consent/rules message on first `/start`
  (e.g., "be respectful, no explicit content, admins can ban for abuse")
  since this will be used by students.

## Driving adoption — what's built in

- **`/menu` and tap-buttons everywhere**: nobody needs to memorize commands.
  `/start`, `/menu`, `/help`, and every "what's next?" prompt shows the same
  button grid, so the bot always has a next action one tap away.
- **Points + daily streaks**: profile completion, likes, matches,
  Friendship Questions pairings, Anonymous Night submissions, and Smash or
  Pass votes all award points (see the `POINTS` dict in `bot.py` to tune
  amounts) and build a daily streak — being active two days running keeps
  the streak alive, missing a day resets it to 1.
- **Badges**: crossing a points or streak threshold (10, 50, 100, 250, 500,
  1000 points; 3, 7, 14, 30-day streaks — see `POINT_BADGES` and
  `STREAK_BADGES` in `bot.py`) sends the member an instant "🎖️ New badge
  unlocked" DM, and the badge icons show next to their name on
  `/leaderboard`. This is the main moment-to-moment hook — people come back
  to chase the next badge.
- **`/leaderboard`**: top 10 by points with badge icons, plus the
  requester's own points, streak, and badges at the bottom.
- **Smash or Pass**: a lightweight, always-available game using generic
  funny prompts (never real member photos or identities), so there's
  something quick to do even without a match or a paired partner.
- **Automatic daily reminder**: once `/setreminder HH:MM <message>` is set,
  the bot pings every verified member at that time every day — no admin
  action needed. `/reminderon` / `/reminderoff` toggle it, `/remindernow`
  fires it on demand for testing or a same-day push. It's on by default
  at 18:00 server time with a generic nudge until you customize it.
- **`/broadcast`**: for one-off announcements outside the daily rhythm —
  e.g., "New batch of members just joined, go browse!"

Cheap growth moves worth doing outside the bot itself: pin `/gencode`
codes and a short "what this bot does" blurb in the WhatsApp group, and
have admins post the weekly leaderboard screenshot there.

## Automatic daily reminder — how it works

- Requires the `job-queue` extra, already in `requirements.txt`:
  `pip install "python-telegram-bot[job-queue]"` (this pulls in
  APScheduler, which `python-telegram-bot`'s `Application.job_queue` uses
  internally).
- On startup, the bot reads `reminder_time`, `reminder_message`, and
  `reminder_enabled` from its `settings` table and schedules a daily job
  at that time. Defaults: `18:00`, a generic "come play a round" message,
  enabled.
- `/setreminder 19:30 Anonymous Night is open tonight — send yours!`
  updates the time and message and reschedules immediately, no restart
  needed.
- If the `job-queue` extra isn't installed, the bot logs a warning at
  startup and simply skips scheduling — everything else still works, and
  `/broadcast` and `/remindernow` remain available as manual fallbacks.
- The schedule uses the server's local time zone (whatever `TZ` the host
  is set to). If you deploy on a host in a different time zone than
  Nigeria, set `TZ=Africa/Lagos` in your environment so `HH:MM` matches
  what your members expect.

## Anonymous Night — how it works

- A member runs `/anonymous`, writes a message, and it's forwarded live to
  every admin in `ADMIN_IDS` with a sequential submission number
  (e.g., "submission #7").
- **Nothing links the message to the sender anywhere in this bot** — the
  sender's Telegram ID is never stored or forwarded, by design, per your
  request that it be anonymous even from admins.
- **Trade-off to be aware of**: because of that, if someone submits
  something abusive, admins can't trace or ban that specific person through
  this feature — there's no identity to act on. The one lever you have is
  `/nightclose`, which shuts off submissions for everyone immediately if
  the feature is being misused, and `/nightopen` to reopen it later.
- Consider pairing this with a pinned reminder in the WhatsApp group about
  what's off-limits (harassment, threats, naming people to hurt them),
  since community norms are the main deterrent here, not traceability.

## Friendship Questions — how it works

- A member runs `/friendquestion`. If someone else is already waiting,
  they're paired immediately and both get a shared set of icebreaker
  questions plus each other's Telegram username.
- If nobody's waiting, they're added to a queue and notified as soon as a
  match is found.
- `/leavequeue` removes them from the waiting pool.
- Question sets are pulled randomly from `FRIENDSHIP_QUESTION_SETS` in
  `bot.py` — edit that list to add your own DTZ TRIO-flavored questions.

## Points, streaks & badges — how they're calculated

- Every scoring action goes through `award_points()`, which also updates
  the caller's daily streak: same-day activity holds the streak, activity
  on the very next calendar day increments it, and a gap resets it to 1.
- Point values per action live in the `POINTS` dict in `bot.py`:
  profile complete (10), like (2), match (15, both sides), Friendship
  Questions pairing (5, both sides), Anonymous Night submission (3),
  Smash or Pass vote (1). Edit these directly to rebalance.
- Badge thresholds live in `POINT_BADGES` and `STREAK_BADGES` in
  `bot.py`. The moment a member's points or streak crosses a new
  threshold, `award_and_notify()` sends them a DM and the icon appears
  next to their name on `/leaderboard` from then on.
