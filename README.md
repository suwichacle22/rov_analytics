# rov_analytics

Team draft statistics for RoV (Arena of Valor) pro play, built from broadcast screenshots.

Two programs share one data model. This repository holds the first one, the **extractor**, which runs on your PC. It also has a local Dashboard page that shows the statistics of the games on this PC. The public dashboard (TanStack Start plus Convex) comes later and reads what the extractor writes. Spec: `docs/rov-draft-stats-spec.pdf`.

## Extractor

Two words are used throughout. A **match** is two teams meeting in a best of five or seven, for example FS vs TEN. A **game** is one game inside it, G1 to G7. Names in code and storage still say `series` for a match: `seriesId`, `data/series/`, `series.json` and the Convex `series` table.

Python 3.12 or newer and uv.

```
python -m uv sync
python -m uv run rov-extract serve
```

Open http://127.0.0.1:8787. On Windows, double-click `RoV Extractor.cmd` instead: it installs dependencies on first run, starts the server and opens the browser. Close its window to stop.

The launcher starts with `--reload`, so a change to any Python file under `src/` restarts the server on its own; edits to the HTML, CSS and JavaScript need only a browser reload. Changes under `data/` never restart it. The launcher also starts with `--lan`, so a phone on the same Wi-Fi can open the app too. The window prints the address, for example `http://192.168.1.110:8787`. Both the editor and the Heroes page have a phone layout; on a phone the checks and the Save button sit in a sheet at the bottom. Only devices on your network can reach it, there is no login, and the first start may show a Windows Firewall prompt for Python where you should allow private networks. Leave `--lan` off to keep it on this PC only.

The page has three columns: matches on the left, the game in the middle as four numbered steps, and the checks on the right with the Save button. Game tabs sit in the top bar. The address bar holds `#<match>/<game>`, so a reload or a bookmark reopens the same game.

1. **New match.** Tournament, match type (Regular season, Leg 1, Leg 2, Playoff, Final), best of, date, both teams, and which team is home. Patch and source link are optional. The source link is the video the match was taken from, for example the YouTube broadcast. It is stored once for the match, not per game, and can be changed later in the Source link field under the match title. This creates `data/series/<date>_<A>-<B>/series.json`.
2. **Game setup and screenshots.** Blue side, winner, duration, and an optional patch. Drop the two screenshots in (draft bar before the swap, post-game stats screen). They are copied into the match folder, and stored in Convex as well when it is configured.
3. **Draft.** Enter each slot as the screen shows it, left to right. Each slot shows the hero art once chosen, the badge gives the pick number and step, and the slot for the next step in draft order is outlined. The name under a pick is the player who played that hero. It is read from the post-game table and cannot be typed here. Type a few letters of a hero name and press Enter to move on in draft order. The strip under the bar is the 18-step sequence.
4. **Post-game.** One row per player: name, the hero played, lane (filled from the Teams page when the player is listed there), K/D/A, damage, and the team totals. Numbers accept `48.25k`. This table is the only source for who played which hero. "Prefill names" copies the names under the draft bar into empty name fields and nothing else.
5. **Save.** The checks column must show no errors. Ctrl+S or the Save button writes `g<N>.json`. Warnings do not block saving. A step's number fills in white when that step is complete.

Everything you type is autosaved to `g<N>.draft.json` while you work. Drafts are gitignored, saved games are committed.

### Recognise

With one or both images attached, press **Recognise**. It never saves. Amber borders mark guesses to check, green ones confident values.

A bar under the button shows the percent done and the part being read. The percent is an estimate from the usual cost of each step, corrected by the speed of this PC as the run goes.

The result belongs to the game that asked for it. If you open another game while it runs, that game is left alone and the values are filled in when you open the first game again. Reloading the page while it waits drops the result, so press Recognise again.

- **Empty fields** are filled.
- **Heroes it is sure about** replace what the field holds, and the message lists every correction. A field that repeats a hero placed elsewhere for certain is cleared.
- **Fields you set by hand** since the page was opened are kept.
- **A hero it cannot name** stays empty with the closest candidates listed first in that slot's search box. An empty field asks for your choice; a wrong name would hide the problem.

What is read:

- **From the draft bar:** the caption (game number, teams), the seat names, and the hero of each of the 18 slots.
- **From the post-game screen:** winner, duration, each player's name, K/D/A, damage dealt and taken, the five team totals, the eight bans again, and the hero in each portrait.

#### How heroes are named

The broadcast draws every hero from the same splash art as `data/ref/art/heropick`, zoomed and cropped differently per hero. A pick shows the upper body, a ban icon and a post-game portrait show the face. `artmatch.py` searches for the crop inside each splash at several zoom levels. The right hero scores 0.8 to 1.0 and the others stay near 0.6.

- **One hero, one slot.** The 18 slots are decided together, best matches first. No hero is proposed twice in a game.
- **Global Ban-Pick.** A team is never offered a hero it picked in an earlier saved game of the match, except in game 7 of a best of seven.
- **Second opinions.** Each ban is read from the draft bar and from the post-game header, and the better reading counts. A pick is lifted when a post-game portrait of the same team shows that hero for certain.
- **Confident** means a score of 0.80 or more with the next hero at least 0.12 behind. Below 0.62 nothing is proposed.
- **Forms of one hero.** Flowborn (Carry) and Flowborn (Mage) show the same artwork. Only the small white badge in the top right corner differs, a bow or a flame, so between forms the badge decides and the artwork does not. The badge is taken from crops of confirmed games, because the broadcast draws it differently from the seed art. A form whose badge was never seen is proposed as a guess when the badge on screen is none of the known ones. Heroes count as forms of one hero when their names differ only in the bracket.

A hero with no art in the seed set, or with newer art, cannot be named the first time. Choose it by hand and save the game. The crop of that slot is then kept in `data/ref/crops` and the hero is recognised from then on. Crops are kept only for slots the artwork did not already name, so the folder stays small. `rov-extract relearn` rebuilds it from all saved games. `rov-extract recognise <match> <game>` prints the raw proposal.

#### Seats and players

The name under a pick on the broadcast is the seat that made the pick. After a swap it is not the player who plays the hero. The post-game screen shows the truth. So every pick in a saved game carries `player` and `lane` from the post-game table, and the seat name is kept separately as `preSwapPlayer`. Each post-game row is tied to a pick through the hero in its portrait, and through image comparison when that hero has no art.

### Teams page

The **Teams** link in the top bar opens the team master: one card per team with its players and the position each one plays (DSL, JGL, MID, ADL, SUP). Add, rename or remove players and press Save. It is stored in `data/ref/players.json`.

- The game form fills the lane of a post-game row from here as soon as the row has a player name. A lane you choose by hand is kept.
- Recognise reads player names against these lists, so a name spelled here is the spelling that lands in the form.
- Saving a game adds player names that are not listed yet, without a position.
- A card says which positions have no player yet.

### Dashboard

`/dashboard` (the Dashboard link in the top bar) shows the draft statistics of one team, computed on every load from the games in `data/series`. Choose the team and the match type in the filter row; the address keeps both, for example `/dashboard?team=FS&stage=leg1`.

- **What counts.** A saved game counts as checked. A game that only has a draft, for example straight from Recognise, is included too and the notice at the top says how many of those there are. A slot without a hero is left out of the hero tables and counted in the notice. A game chip in the Matches table opens that game in the form.
- **Sections.** Record by match, game and side, and average game time. Picks with won and lost and who played the hero. Picks against the team. Hero pool of each player. Bans by and against the team, split by ban phase. First pick on blue side, first two picks on red side, and the opponent's first pick. Position by pick order. Answers to an opponent pick: the hero the team picked in its next turn, for pairs seen at least twice. Most contested heroes. Per-game totals and player averages.
- **Who played a hero** comes from the post-game table, so a swap after the draft is already counted for the right player. Position by pick order needs the positions from the Teams page.
- The numbers come from `team_stats` in `src/rov_extractor/stats.py`, served at `/api/stats?team=&stage=`. The public dashboard should use the same definitions.

### Heroes page

The **Heroes** link in the top bar opens a table of every hero with its ban icon, its pick art, its id and name, and the broadcast crops learned so far. Use it to confirm each hero is paired with the right image: pick another file from the dropdown when one is wrong, tick **Checked** or double-click the row (double-tap on a phone) when it is right, rename or remove heroes, or add a new one. Rows without art are highlighted, and files that no hero uses are listed at the bottom. The pairing is saved to `data/ref/art-map.json` and the recogniser reads it from there. When Convex is configured, every Save also mirrors the hero list (id, name, forms, checked, whether art exists) into the `heroes` table for the dashboard; `rov-extract push --heroes` does the same from the command line. Each hero's ban icon and pick art are uploaded to Convex file storage once, their storage ids are cached in `art-map.json`, and only files you change are sent again. The dashboard reads `heroes:listWithArt` to get names and image URLs.

You can also teach the recogniser directly from this page. Drop a crop from a broadcast screenshot on a hero's row (a tall crop is stored as a pick splash, a roughly square one as a ban icon), or use the "+ ban" and "+ pick" buttons. Hovering a learned crop shows a delete button for wrong ones.

Draft-bar images can be a tight crop of the bar or a full 16:9 frame. Post-game images must be a full 16:9 screenshot. Geometry for the RPL 2026 broadcast is in the layout file; a new broadcast design needs a new layout.

### Draft order

RPL 2026 slots fill in draft order, blue from the left inward and red from the right inward:

| | Screen slot 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| Blue bans | B1 | B3 | B6 | B8 | |
| Red bans | B7 | B5 | B4 | B2 | |
| Blue picks | P1 | P4 | P5 | P8 | P9 |
| Red picks | P10 | P7 | P6 | P3 | P2 |

Sequence: bans 1 to 4, picks 1 to 6, bans 5 to 8, picks 7 to 10. The mapping lives in `data/ref/layouts/rpl2026.json`; add a new layout file if a broadcast changes.

### Checks before save

- 4 bans and 5 picks per side, 18 actions, every hero known.
- No hero twice in a game. Flowborn is one hero per form (Flowborn (Carry), Flowborn (Mage), add more on the Heroes page), so its forms are drafted and counted separately.
- Global Ban-Pick: a team cannot pick a hero it picked earlier in the same match, except game 7 of a Bo7.
- Five distinct players and five distinct lanes per team, and the post-swap heroes must equal that team's picks.
- Winner and duration set.

### Screenshots

Attach a screenshot by clicking a box, dropping a file on it, or pasting. Ctrl V puts a copied image into the box under the pointer, or into the first empty box when the pointer is elsewhere. Each box also has a Paste button when the page is open on `localhost` or `127.0.0.1`; browsers do not allow that button on a plain network address, where Ctrl V still works.

The original file name is not kept. Every screenshot is stored as `<teamA>_vs_<teamB>_<match type>_g<N>_<draft|post>.<ext>`, for example `FS_vs_BRU_leg1_g1_draft.png`. Changing the match type renames the files of that match, the names inside its game files, and the records in Convex. Files named the old way (`g1_draft.png`) are still found.

### Screenshots from the source video

```
python -m uv run rov-extract grab <match> [--game N] [--force] [--dry-run]
```

`grab` takes both screenshots of every game straight from the match's source link. The Garena broadcasts on YouTube have a chapter where each draft starts and one where each game starts, and the team pair in the chapter title finds the games of this match. A missing chapter is estimated from the other one of that game, and the line for that game says so.

- **Draft.** Between the draft chapter and a minute after the game chapter it looks for the first frame where all ten picks are filled and the blue turn marker under the team logos is gone. That is the moment the last pick locks and the swap phase starts. The screenshot must show the start of the swap phase, with the timer on the bar just reset to 00:59 (00:57 at the latest) and no hero swapped yet; a draft where no such frame is found is reported and not attached. The caption must name both teams and the right game.
- **Post-game.** From 5 minutes after the game chapter until the next draft, the next match or 60 minutes, it looks every 5 seconds for the full-screen GAME STATS screen. It takes the frame in the middle of the time the screen is shown, where the game time, VICTORY or DEFEAT and all 20 damage numbers can be read.

Frames are saved as 1080p PNG files under the usual names and uploaded to Convex like a screenshot attached in the app. A game that already has a screenshot of that kind keeps it unless you pass `--force`. `--dry-run` prints the times and attaches nothing. Each game gets one line with the times it chose (h:mm:ss in the video), and a `?` with a reason under it when something did not check out. Look at those screenshots before you press Recognise.

Only the parts of the video it needs are downloaded: the scan runs on the 144p and 360p streams, five seconds at a time, and only the chosen frames come from the 1080p stream. No ffmpeg is needed. It takes about a minute per game. Temporary files go to `data/grab_tmp/` and are removed at the end.

### Match date

The screenshots show no date, so the day of a match is read from its source link. The New match dialog fills the date as soon as a source link is entered; while the video is being read, the Create match button says "Reading the date…" and is disabled, and a submit sent in that moment waits for the date, so a match is never created with today's date by accident. Recognise checks it again and corrects the match when the video says another day. A date typed by hand, in the dialog or in the Date field under the match title, is kept and never replaced. A match without a source link keeps the date it was created with. The day is taken in Thai time (`BROADCAST_TZ` in `src/rov_extractor/source.py`).

The id of a match, and with it the folder name, is fixed when the match is created and keeps that day. A second match that would get the same id takes a number, for example `2026-09-29_FS-KOG-2`.

### Match type

Every match has a match type: Regular season, Leg 1, Leg 2, Playoff or Final. It is stored as `stage` in `series.json` (`regular`, `leg1`, `leg2`, `playoffs`, `final`). Choose it in the New match dialog, or change it later with the Match type field under the match title. Changing it also updates the saved games of that match and pushes them to Convex again. The list lives in `STAGES` in `src/rov_extractor/models.py`.

### Deleting

Each match in the left rail has a menu button with Delete match. The open game has a menu button beside the score with Delete game N and Delete match. Both ask for confirmation.

- Delete game removes that game's saved record, draft, recognition proposal and screenshots, and the hero crops learned from it. The other games of the match stay and the match score is recomputed.
- Delete match removes the whole match folder.
- With Convex configured the same rows and stored screenshots are removed there first (`games:removeGame`, `games:removeSeries`). If Convex does not answer, nothing is deleted.

### Command line

```
python -m uv run rov-extract list                 # matches and games on disk
python -m uv run rov-extract validate [match]     # re-run the checks on saved games
python -m uv run rov-extract push [match] [--game N]
```

```
python -m uv run rov-extract purge-images [match] [--dry-run]   # drop local screenshots already in Convex
```

`push` sends a saved game to Convex through the mutation `games:upsert` and uploads its screenshots if they are not stored yet. Put `CONVEX_URL=https://<deployment>.convex.cloud` in `.env.local`, or for a self-hosted Convex `CONVEX_SELF_HOSTED_URL=http://<host>:3210` and `CONVEX_SELF_HOSTED_ADMIN_KEY=...`.

### Convex backend

Each pick in the `draftActions` table has `player` and `lane` (who played the hero, from the post-game table) and `seatPlayer` (the seat that made the pick). Use `player` for every statistic about players. The `by_player` index serves those queries.

Each row of the `series` table has `vodUrl`, the source link of the match.

The functions live in `convex/` at the repo root: `schema.ts` (series, games, one row per draft action, images), `games.ts` (`upsert`, `remove`, `listSeries`, `bySeries`) and `files.ts` (upload URL, `saveImage`, `imageUrl`, `listImages`). Deploy them with Bun:

```
bun install
bunx convex deploy
```

The CLI reads the same variables from `.env.local`. Screenshots attached in the app are copied into the match folder and, when Convex is configured, uploaded to Convex file storage at the same time. The local copy is a cache: `purge-images` deletes the ones already stored, and the app or `recognise` downloads a file again when it needs it. The hero art and learned crops stay local.

### Reference data

`data/ref/heroes.json` (hero ids and names; Flowborn forms are separate heroes), `teams.json` (RPL 2026 Winter), `players.json` (rosters, grows automatically as you save games), `tournaments.json`, `layouts/`. Edit these by hand when a hero or team is added.

### Game JSON

One file per game. `draft` is the 18-step sequence with `seq`, `phase`, `side`, `team`, `action`, `hero`, `slot` and, for picks, the pre-swap player name shown on the bar. `players` holds the post-swap hero per player with lane and stats. `input` keeps the raw form state so the game can be reopened and edited.

## History

The repository previously held a minimap position tracker. It was removed on 24 September 2026 and lives in git history before that commit.
