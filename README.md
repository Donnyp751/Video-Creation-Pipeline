# kids-video-ai

A local-first AI pipeline for making bilingual (e.g. Vietnamese and English) music-video cartoons for young children.

```
project.yaml → Creative Director → language QA → ⏸ lyrics
            → music → timing alignment → storyboard → ⏸ storyboard
            → scene images → AI visual QA → ⏸ images
            → image-to-video → AI video QA → ⏸ videos
            → FFmpeg render (preview) + automated QC → ⏸ preview
            → final render + QC → thumbnail → youtube.json
```

**Core rule:** every stage writes persistent artifacts into `projects/<id>/`, and the next stage reads them from there. You never copy prompts between apps. Every stage can be run on its own from the CLI or the dashboard, and re-running only does work that is missing.

## Quick start

```bash
# Requirements: Python 3.12+, ffmpeg/ffprobe on PATH, uv (or pip)
uv sync --extra dev
source .venv/bin/activate

# 1. Free dry run with offline mock providers (no keys, no spend)
scripts/mock_demo.sh /tmp/kv-demo        # -> /tmp/kv-demo/projects/demo-song/output/*.mp4

# 2. Real run
cp .env.example .env                     # add your API keys
kidsvideo new fruit-song --title "Trái Cây Gì Đây?" --topic fruit
$EDITOR projects/fruit-song/project.yaml
kidsvideo build fruit-song               # stops at each approval gate; re-run to resume
kidsvideo serve                          # dashboard on http://127.0.0.1:8000
```

`examples/fruit-song-001/project.yaml` is the reference project spec.

## API keys

Keys go in `.env` only. They are never read from `project.yaml` and never committed (`.env` is git-ignored).

| Variable | Used by |
|---|---|
| `OPENAI_API_KEY` | Creative Director, language review, image/video QA (vision), scene images and thumbnails (`gpt-image-1`), timing transcription (Whisper) |
| `ELEVENLABS_API_KEY` | Music generation |
| `RUNWAY_API_KEY` | Image-to-video |

`kidsvideo --mock …` or `KIDSVIDEO_MOCK_PROVIDERS=1` swaps every provider for an offline mock. You only need a key once you run that stage for real.

> **Note:** the OpenAI, ElevenLabs Music and Runway integrations follow those vendors' documented APIs, but they have not yet been tested against the live services. Test runs used the mock providers. Expect to adjust small details (model names, parameters) on your first real run. Model names and prices are set in `config/pipeline.yaml`.

## Commands

| Command | What it does |
|---|---|
| `kidsvideo new <id>` | Create `projects/<id>/project.yaml` from `assets/templates/project.yaml` |
| `kidsvideo validate <id>` | Validate the spec |
| `kidsvideo lyrics <id> [--regenerate]` | Creative Director plan, then bilingual language review (suggestions only, never auto-applied) |
| `kidsvideo approve <id> lyrics\|storyboard\|images\|videos\|preview [--scene N] [--all]` | Approval gates |
| `kidsvideo music <id> [--regenerate]` | `audio/song.wav` plus `music_request.json` / `music_response.json` |
| `kidsvideo timing <id>` | Transcribe and align lyrics to the song, writing `timing.json` |
| `kidsvideo storyboard <id>` | Scene start/end times, written to `storyboard.json` |
| `kidsvideo bible <id> [--generate]` | Character Bible skeletons (and reference sheets) |
| `kidsvideo images <id>` / `image <id> --scene N` | Generate missing images, or a new version for one scene |
| `kidsvideo review <id> images\|videos [--scene N]` | AI visual QA |
| `kidsvideo select <id> --scene N --image V` | Choose which version to use |
| `kidsvideo videos <id>` / `video <id> --scene N` | Animate approved images |
| `kidsvideo render <id> --preset preview\|youtube\|youtube_shorts` | FFmpeg render plus automated QC |
| `kidsvideo subtitles <id>` | `subtitles/vi.srt`, `en.srt`, `bilingual.srt` |
| `kidsvideo thumbnail <id> [--pick N]` | Text-free candidates, then title typography added with Pillow |
| `kidsvideo metadata <id>` | `youtube.json` with alternate titles (`made_for_kids` is always true) |
| `kidsvideo status <id>` / `costs <id>` | Stage, approval, scene and cost overview |
| `kidsvideo build <id>` | Everything in order, stopping at each gate |
| `kidsvideo serve` | Web dashboard |

Global flags: `--mock` (offline providers), `--no-cache` (bypass the request cache) and `--ignore-gates` (for development).

## Project layout on disk

```
projects/fruit-song/
├── project.yaml               # ProjectSpec (human-authored)
├── state.json                 # approvals (with hash of what was approved)
├── creative_plan.json         # lyrics + scenes (history/ keeps old versions)
├── language_review.json
├── audio/ song.wav  song_v1.wav  song_raw_v1.mp3  music_request.json  music_response.json  transcript.json
├── timing.json  storyboard.json
├── scenes/004/
│   ├── prompt.txt  prompt_override.txt      # compiled prompt / your edit
│   ├── image_v1.png  image_v2.png  selected.png
│   ├── animation_prompt.txt  animation_v1.mp4  selected_video.mp4
│   └── metadata.json                        # versions, selection, AI reviews, status
├── subtitles/  vi.srt  en.srt  bilingual.srt
├── render/<preset>/ final.mp4  filter_graph.txt  render.json  qc.json
├── thumbnail/  candidate_v1.png …  selected.png
├── output/fruit-song-youtube.mp4
└── youtube.json
assets/characters/<id>/character.yaml (+ front.png, reference_sheet.png, …)   # Character Bible
data/kidsvideo.db  data/cache/                                               # costs, jobs, request cache
```

## Architecture notes

- **Code layout:** `app/models` holds the Pydantic schemas (ProjectSpec, CreativePlan, reviews, timing, state). `app/providers` holds the provider families. `app/services` has one module per stage. `app/pipeline` holds the context, gates, `build`, the job queue and status. Then there are `app/api` (FastAPI), `app/cli.py` and `frontend/` (plain HTML/JS, no build step).
- **Providers** (`app/providers/{llm,image,music,video,speech}`): each family has an abstract base, real implementations and a mock. `project.yaml → providers:` chooses an implementation by name via `providers/registry.py`. To add a provider, implement the base class and register it; pipeline code does not change.
- **Caching and cost tracking are applied around every provider call** (`providers/tracked.py`), so services do not deal with either. The cache key is a hash of provider + model + operation + prompt + parameters + the *content* of reference images. Deliberate regenerations include the version number in the key, so they are real new requests. Each call (including cache hits and failures) is recorded in SQLite with tokens/units and an estimated cost from `config/pipeline.yaml`.
- **Structured LLM output:** responses are validated against Pydantic models, plus semantic checks (e.g. character ids exist, scenes cover every lyric line in order). Invalid output is retried with the validation errors fed back to the model.
- **Deterministic prompt compiler** (`services/prompt_compiler.py`): the LLM decides *what happens*. STYLE, CHARACTERS (from the Character Bible, including `never_change`), ENVIRONMENT, SCENE, COMPOSITION and CONSTRAINTS are assembled the same way every time.
- **Timing:** the song is transcribed with word timestamps, and the *known* lyrics are matched against the transcript using accent-insensitive sequence matching. Lines that can't be matched are interpolated. Scenes then fill the song exactly: `scene.duration = next_scene.start - scene.start`.
- **Gates are hash-based:** an approval stores the hash of what was approved. Editing the plan or regenerating the storyboard makes the approval stale automatically. Image and video gates are per scene, and regenerating an image flags that scene's animation for review.
- **Renderer:** `build_render_plan()` is a pure function that produces the FFmpeg filter graph: normalisation, last-frame hold for clips that are too short, crossfades placed at the exact scene boundaries (so audio stays in sync), loudnorm to −14 LUFS, burned-in subtitles, and intro/outro. The graph is saved next to every render.
- **QC:** checks duration vs. song, resolution, fps, audio/video streams, integrated loudness, long black segments and long silences.
- **Jobs:** the dashboard submits long work as SQLite-backed in-process jobs (QUEUED → GENERATING → DOWNLOADING → REVIEWING → COMPLETE/FAILED). Redis/Celery can replace this later without touching services.

## Tests

```bash
pytest -q          # ~1 minute; uses mock providers + real ffmpeg, spends nothing
ruff check app tests
```

The tests check contracts, not exact AI text: spec validation, plan coverage rules, retry-with-errors, prompt compiler, alignment, subtitles, filter-graph math, cache and cost accounting, the API, and a full mock build through every approval gate to a QC-passing MP4.

## Milestones

| | Status |
|---|---|
| M1 Repo + ProjectSpec + CLI | done |
| M2 LLM → bilingual lyrics + storyboard JSON (+ language QA) | done |
| M3 Character Bible + prompt compiler | done |
| M4 Image API + batch generation + versioning | done |
| M5 Music API + song storage | done (ElevenLabs not yet tested live) |
| M6 Audio timing/alignment + scene timing | done |
| M7 Image-to-video API | done (Runway not yet tested live) |
| M8 FFmpeg → complete synchronized video | done with mocks. **Next: one real fruit-song video end to end** |
| M9 AI image/video QC + approval workflow | done |
| M10 Dashboard + thumbnails + subtitles + cost tracking | first version done |
