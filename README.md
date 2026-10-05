# rov_analytics

Team draft statistics for RoV (Arena of Valor) pro play, built from broadcast screenshots.

Spec: `docs/rov-draft-stats-spec.pdf`.

## Layout

One repository, three parts. Code that runs somewhere on its own is an app, code that apps share is a package.

```
apps/
  extractor/     Python. Screenshots in, checked games out. Runs on your PC only.
  web/           TypeScript. TanStack Start and Tailwind. The dashboard.
packages/
  backend/       TypeScript. Convex schema, queries and mutations.
data/            Screenshots, drafts, saved games and reference data of the extractor.
docs/
server/             up.sh starts everything on a Linux server, send.cmd brings the data there.
docker-compose.yml  The same two parts as containers, for server/up-docker.sh.
RoV Extractor.cmd   Starts the extractor on the PC.
package.json        Bun workspace: apps/* and packages/*.
.env.local          Convex address and key. Never committed.
```

How a game travels:

1. The extractor recognises and checks a game on your PC, and you save it.
2. **Push to Convex** in the extractor, or `rov-extract push`, sends the game to Convex.
3. The backend functions in Convex turn the games into statistics.
4. The web app asks Convex for the statistics and shows them. A game pushed later shows up in an open dashboard without a reload.

The source of the backend lives in `packages/backend`, and a deploy copies it to the Convex deployment, where it runs next to the database. The web app does not contain the functions. It imports only their names and types from `@rov/backend`, so a change to the schema or to a function shows up in the dashboard as a type error.

Each part goes to a different place:

| Folder | Runs on | How it gets there |
|---|---|---|
| `apps/extractor` | Your PC, or a Linux server | `RoV Extractor.cmd`, or `server/up.sh` |
| `packages/backend` | Convex | `bun run backend:deploy` |
| `apps/web` | Your PC, or a Linux server | `bun run dev`, or `server/up.sh` |

Only the web app is meant to be public. The extractor has no login and stays on your network. The Convex key stays in the root `.env.local`; `apps/web/.env.local` holds only the address.

### Commands from the repo root

```
bun install              # once, and after a dependency changes
bun run dev              # the dashboard on http://localhost:3000
bun run backend:deploy   # send the Convex functions to the deployment in .env.local
bun run typecheck        # type-check the backend and the web app
bun run build            # production build of the web app
```

### Running on a Linux server

The dashboard and the extractor run as two services of your own user, `rov-web` and `rov-extractor`, that start again after a crash and after a reboot. No Docker and no sudo. The server needs git, curl and systemd; `up.sh` installs uv and Bun into your home folder when they are missing. Convex stays where it is.

1. On the server: `git clone -b monorepo https://github.com/suwichacle22/rov_analytics.git`
2. Copy `.env.local` from the PC into the repo folder on the server. It holds the Convex address and key, and git does not carry it.
3. On the server: `./server/up.sh`

`up.sh` installs the packages, builds the dashboard, writes and starts both services and prints the two addresses. Nothing else has to be carried over: when the extractor starts it fetches the matches, games, rosters, hero art and crops from Convex, and a screenshot when a game needs it. `server\send.cmd user@server` on the PC is a shortcut for steps 2 and 3 that also copies the screenshots, so they need not be fetched one by one. It expects the repo in `~/rov_analytics`; give another folder as the second argument.

| | Port | Change it in `.env` on the server |
|---|---|---|
| Dashboard | 3000 | `WEB_PORT=...` |
| Extractor | 8787 | `EXTRACTOR_PORT=...` |

- **Updating.** On the server, `git pull` and `./server/up.sh`.
- **The data lives in Convex.** The PC and the server each keep a copy of the matches and games, and both stay in step with Convex while the extractor runs, see Convex below. An edit on one machine shows on the other after a reload. `send.cmd` refuses to run a second time, because it would put the PC's files over the server's; `server\send.cmd user@server again` does it anyway.
- **The Convex address.** The dashboard is built with the address from `.env.local`, and every browser that opens it talks to Convex directly, so the address has to work from the browsers too. If the server cannot find the name in the address, `up.sh` says so; write the IP address into `.env.local` then.
- **The Convex functions** are not deployed from the server. `bun run backend:deploy` on the PC does that, as before.
- **Looking inside.** `systemctl --user status rov-extractor rov-web`, and `journalctl --user -u rov-extractor -f` for the log. `systemctl --user disable --now rov-extractor rov-web` stops both for good.
- The extractor has no login. Keep port 8787 inside your network.

## Dashboard (apps/web)

`bun run dev` opens the dashboard at http://localhost:3000. The root address is the league page; each team has its own page, `/teams/<id>`, for example `/teams/FS`. A match type is chosen with `?stage=leg1`, and the control for it appears once there are games in more than one match type. It needs `apps/web/.env.local` with `VITE_CONVEX_URL`, see `.env.example` there.

- **League page.** Standings ordered by matches won, then game difference, with each team's games as marks in its own colour and its signature heroes, the ones it picks at least twice as often as the league. Blue side against red side over every game. The hero pool: every hero picked or banned, how often it is in a draft, and the record of the side that picked it. A few sentences on what stands out, written by rules in `src/components/league.tsx`. The numbers come from the Convex query `stats:league`, computed in `packages/backend/convex/lib/leagueStats.ts`.
- **Teams and their colour.** Every team in the Convex `teams` table has a page; the switcher in the top bar lists them all, with the league page first. `src/lib/teams.ts` holds the colours of each: the accent, the text colour on top of it, and the background. The accents are taken from the team logos on the broadcast (Full Sense orange, Buriram blue, Bacon Time pink, King of Gamers white, Hydra light blue, eArena pink, Tenacity teal, SOLYX gold, Godji Check green). A team without an entry gets the default grey.
- **How colour is used.** Black, greys and the one team colour. The team colour marks the team's wins and the team's own numbers, nothing else. A loss is a hollow ring, not a second colour, and the side of a game is written out as B or R. So the page stays readable with any team colour and for colour-blind readers.
- **One mark is one game.** Counts and records are drawn as a row of marks, filled for a win and hollow for a loss, instead of a bar beside a percentage. With this few games a percentage suggests more than the data holds, and the marks can be counted. A row shows the games behind it on hover or with the Tab key.
- **Order of the page.** The answer first, details after: Overview with the win rate, a few sentences on what stands out, every game in order, the two sides and the game times. Then Picks with the hero pool of each player, Bans, Draft, Players and Matches. A match opens to show the draft of each game, and in "Every game, in order" pointing at a match, or moving to it with the Tab key, shows the drafts of all its games in a box laid out like the broadcast bar (`src/components/peek.tsx`). The sentences under "What stands out" are written by rules in `src/components/overview.tsx`, each with a minimum number of games.
- **Picks are counted per match.** A team can pick a hero once per match, so a pick shows "7 of 8 matches" beside its games.
- **What counts.** A saved game counts as checked. A game pushed as a draft with `rov-extract push --drafts` is included too, and the notice at the top says how many of those there are. Saving and pushing the game later replaces its unchecked copy. A slot without a hero is left out and counted in the notice.
- **Who played a hero** comes from the post-game table, so a swap after the draft is already counted for the right player. The position by pick order needs the positions from the Teams page of the extractor.
- **Where things are.** The league page is `src/routes/index.tsx` with its parts in `src/components/league.tsx`. The team page is `src/routes/teams.$teamId.tsx`. Its sections are in `src/components/`: `overview.tsx`, `picks.tsx`, `bans.tsx`, `draft.tsx`, `players.tsx` and `matches.tsx`, with the shared pieces in `ui.tsx` and `hero.tsx`. The base colours are the theme in `src/styles.css`. The numbers come from the Convex queries `stats:league`, `stats:dashboard` and `games:drafts`, see Backend below.

## Backend (packages/backend)

The Convex functions in `packages/backend/convex/`:

- `schema.ts`: the tables `series`, `games`, `draftActions` with one row per draft action, `heroes`, `teams` and `images`.
- `games.ts`: `upsert`, `remove`, `removeGame`, `removeSeries`, `listSeries`, `bySeries`, and `drafts`, the draft of every game of one match for the dashboard. `heroes.ts` and `teams.ts` mirror the reference data. `files.ts` handles the screenshots.
- `stats.ts`: the query `dashboard`, which the web app calls. The calculation itself is `lib/teamStats.ts`, plain functions without database access.
- `lib/ref.ts`: lane and match type names, shared with the web app as `@rov/backend/ref`.

`bun run backend:deploy` sends them to the deployment named in the root `.env.local`: `CONVEX_URL=https://<deployment>.convex.cloud` for Convex Cloud, or `CONVEX_SELF_HOSTED_URL=http://<host>:3210` and `CONVEX_SELF_HOSTED_ADMIN_KEY=...` for a self-hosted Convex. The extractor reads the same file. The generated folder `convex/_generated` is committed, because the web app imports its types.

Each pick in the `draftActions` table has `player` and `lane` (who played the hero, from the post-game table) and `seatPlayer` (the seat that made the pick). Use `player` for every statistic about players. Each row of the `series` table has `vodUrl`, the source link of the match. A `games` row has `checked`, false for a game that was pushed as a draft.

## Extractor (apps/extractor)

Two words are used throughout. A **match** is two teams meeting in a best of five or seven, for example FS vs TEN. A **game** is one game inside it, G1 to G7. Names in code and storage still say `series` for a match: `seriesId`, `data/series/`, `series.json` and the Convex `series` table.

Python 3.12 or newer and uv. Every `rov-extract` command runs from `apps/extractor`:

```
cd apps/extractor
python -m uv sync
python -m uv run rov-extract serve
```

Open http://127.0.0.1:8787. On Windows, double-click `RoV Extractor.cmd` in the repo root instead: it installs dependencies on first run, starts the server and opens the browser. Close its window to stop. The extractor finds `data/` and `.env.local` in the repo root on its own.

The launcher starts with `--reload`, so a change to any Python file under `apps/extractor/src/` restarts the server on its own; edits to the HTML, CSS and JavaScript need only a browser reload. Changes under `data/` never restart it. The launcher also starts with `--lan`, so a phone on the same Wi-Fi can open the app too. The window prints the address, for example `http://192.168.1.110:8787`. Both the editor and the Heroes page have a phone layout; on a phone the checks and the Save button sit in a sheet at the bottom. Only devices on your network can reach it, there is no login, and the first start may show a Windows Firewall prompt for Python where you should allow private networks. Leave `--lan` off to keep it on this PC only.

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

#### What you still have to check

A game that is not saved yet shows what needs your eyes. The game tab in the top bar and the game's dot in the match list turn red, and the tab carries the number of values to look at. A draft with nothing flagged stays amber, a saved game is green. The list is at the top of the right column under "To check":

- a hero that Recognise read with a score under 90%, with the score on the slot,
- a hero in the form that is not what Recognise read,
- a slot or a player row without a hero,
- a player name that was matched loosely, with what the screen reads,
- a missing winner or game time.

Click an item to jump to its field. **OK** says the value is right, and "All of these are right" settles every item that can be settled that way. Choosing a hero or a name by hand counts as confirmed too. The confirmation is stored with the draft (`confirmed` on the slot or the player row), so it survives a reload. The rule lives in `review.py`; the threshold is `REVIEW_SCORE`.

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

### Heroes page

The **Heroes** link in the top bar opens a table of every hero with its ban icon, its pick art, its id and name, and the broadcast crops learned so far. Use it to confirm each hero is paired with the right image: pick another file from the dropdown when one is wrong, tick **Checked** or double-click the row (double-tap on a phone) when it is right, rename or remove heroes, or add a new one. Rows without art are highlighted, and files that no hero uses are listed at the bottom. The pairing is saved to `data/ref/art-map.json` and the recogniser reads it from there. When Convex is configured, every Save also mirrors the hero list (id, name, forms, checked, whether art exists) into the `heroes` table for the dashboard; `rov-extract push --heroes` does the same from the command line. Each hero's ban icon and pick art are uploaded to Convex file storage once, their storage ids are cached in `art-map.json`, and only files you change are sent again. The dashboard reads `heroes:listWithArt` to get names and image URLs.

To give a hero its own image, press **Upload** next to the ban icon or the pick art, or drop an image on it. An image on the clipboard works too: press **Paste**, or move the pointer over the icon or the art and press Ctrl+V. The Paste button only shows on `localhost`, because browsers let a page read the clipboard from a button only there; Ctrl+V works on every address. Any image works: it is cut around the middle to the right shape and resized to the size of the other files (72 x 72 for a ban icon, 138 x 250 for pick art), stored in `data/ref/art`, paired with the hero and sent to Convex at once, without pressing Save. A file the hero had before stays on disk and shows up in the list of unused files.

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

### Matches from a list of links

```
python -m uv run rov-extract import [--grab] [--dry-run] [--file <path>]
```

`data/links.txt` holds one broadcast link per line; a playlist link stands for every video in it. `import` reads each video's chapter list, where the Garena broadcast names every match and game ("KOG vs BRU เริ่มดราฟเกม 1"), and creates a match for each team pair that is not on disk yet: the teams from the chapter title, the home team as the first one named, the date from the video, and a source link that opens the video where the match starts. A match already there with the same teams on the same day is left alone, so the command can be run again after adding links. A line `stage: leg1`, `bestof: 5` or `tournament: rpl-2026-winter` applies to the links below it; `#` starts a note. A team name that is not an id in `data/ref/teams.json` is reported and that match is skipped.

With `--grab` it then takes the screenshots of every match it found, see the next section; games that already have theirs are skipped. `--dry-run` only prints what would be created.

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

The screenshots show no date, so the day of a match is read from its source link. The New match dialog fills the date as soon as a source link is entered; while the video is being read, the Create match button says "Reading the date…" and is disabled, and a submit sent in that moment waits for the date, so a match is never created with today's date by accident. Recognise checks it again and corrects the match when the video says another day. A date typed by hand, in the dialog or in the Date field under the match title, is kept and never replaced. A match without a source link keeps the date it was created with. The day is taken in Thai time (`BROADCAST_TZ` in `apps/extractor/src/rov_extractor/source.py`).

The id of a match, and with it the folder name, is fixed when the match is created and keeps that day. A second match that would get the same id takes a number, for example `2026-09-29_FS-KOG-2`.

### Match type

Every match has a match type: Regular season, Leg 1, Leg 2, Playoff or Final. It is stored as `stage` in `series.json` (`regular`, `leg1`, `leg2`, `playoffs`, `final`). Choose it in the New match dialog, or change it later with the Match type field under the match title. Changing it also updates the saved games of that match and pushes them to Convex again. The list lives in `STAGES` in `apps/extractor/src/rov_extractor/models.py`.

### Deleting

Each match in the left rail has a menu button with Delete match. The open game has a menu button beside the score with Delete game N and Delete match. Both ask for confirmation.

- Delete game removes that game's saved record, draft, recognition proposal and screenshots, and the hero crops learned from it. The other games of the match stay and the match score is recomputed.
- Delete match removes the whole match folder.
- With Convex configured the same rows and stored screenshots are removed there first (`games:removeGame`, `games:removeSeries`). If Convex does not answer, nothing is deleted.

### Command line

Run these from `apps/extractor`:

```
python -m uv run rov-extract list                 # matches and games on disk
python -m uv run rov-extract import [--grab]      # create the matches named in data/links.txt
python -m uv run rov-extract validate [match]     # re-run the checks on saved games
python -m uv run rov-extract push [match] [--game N] [--drafts] [--heroes]
python -m uv run rov-extract pull                 # fetch hero art and crops from Convex that this machine lacks
python -m uv run rov-extract sync                 # bring matches and games here and in Convex in step
python -m uv run rov-extract purge-images [match] [--dry-run]   # drop local screenshots already in Convex
```

`push` sends the saved games to Convex through the mutation `games:upsert`, uploads their screenshots if they are not stored yet, and mirrors the team names. With `--drafts` it also sends the games that are not saved yet, marked as unchecked, so the dashboard can show them before you have checked every game. A draft without any hero is skipped. Run it again after you change drafts, because a draft is not pushed on its own. With `--heroes` it mirrors the hero list and art; a hero without art of its own gets its first learned crop as its picture.

### Convex

The extractor reads the Convex address and key from `.env.local` in the repo root, see Backend above. Screenshots attached in the app are copied into the match folder and, when Convex is configured, uploaded to Convex file storage at the same time. The local copy is a cache: `purge-images` deletes the ones already stored, and the app or `recognise` downloads a file again when it needs it.

The heroes live in Convex too: the list, the ban icon and pick art paired with each hero, and every learned crop. Saving the Heroes page, setting art, adding or deleting a crop and saving a game all send the change. In the other direction, the extractor fetches on every start the art files and crops that Convex holds and this machine lacks, and adds heroes missing from `heroes.json`; `rov-extract pull` does the same by hand. That is how a fresh clone gets its heroes, since git carries neither folder. Nothing on disk is replaced, and a file missing on this machine never deletes the stored one.

The matches and games live in Convex in the same way (`sync.py`). Per match that is `series.json`, and per game the form (`g1.draft.json`), the Recognise reading that drives the "To check" list (`g1.proposal.json`) and the saved game (`g1.json`); plus the rosters in `data/ref/players.json`. None of these is in git. One pass compares each file on disk with the copy in Convex and with what both held after the last pass (`data/.sync.json`): a file changed here goes up, a file changed there comes down, and when both changed the newer one wins and the local loser is kept as `<name>.bak`. A pass runs when the extractor starts, a moment after every change made in the app, and when the match list is opened after 20 seconds of quiet; `rov-extract sync` runs one by hand, for example after `grab` or `import` on the command line. Deleting a game here deletes it in Convex. A whole match is only removed by its Delete button; a match folder that is merely missing on a machine is fetched again. Without Convex in `.env.local` nothing is compared and the files stay local.

### Reference data

`data/ref/heroes.json` (hero ids and names; Flowborn forms are separate heroes), `teams.json` (RPL 2026 Winter), `players.json` (rosters, grows automatically as you save games; kept in Convex, not in git), `tournaments.json`, `layouts/`. Edit these by hand when a hero or team is added.

### Game JSON

One file per game. `draft` is the 18-step sequence with `seq`, `phase`, `side`, `team`, `action`, `hero`, `slot` and, for picks, the pre-swap player name shown on the bar. `players` holds the post-swap hero per player with lane and stats. `input` keeps the raw form state so the game can be reopened and edited.

## History

The repository previously held a minimap position tracker. It was removed on 24 September 2026 and lives in git history before that commit.
