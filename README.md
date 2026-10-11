# IsoForge

**A local, free, engine-neutral asset factory for isometric 2.5D games, exposed as an MCP server.**

You describe what you need ("a dilapidated concrete wall set, a cracked asphalt floor, a rusty oil barrel, a zombie with
walk/attack/death animations") and an AI assistant that speaks MCP (Claude Code, Claude Desktop, Cursor, ...) builds it on
your own machine and drops it into whichever game project you are working in: Godot 4, a three.js/Vite web game, Unity,
Unreal, GameMaker, Defold, Tiled, or a plain folder.

No paid services, no cloud, no API keys. Everything runs on one Apple Silicon Mac (developed and tested on a 16 GB M1).

```
 "build a concrete wall set, a barrel, and a zombie, put them in this project"
                               │
                     MCP client (Claude Code, ...)
                               │  stdio
                           IsoForge
        ┌──────────────┬───────┴────────┬─────────────────┐
     Blender        Draw Things        rembg           Godot (optional)
  (structures, 3D,  (AI sprites &    (cut-outs)        (import / verify)
   characters)       textures)
        └──────────────┴───────┬────────┴─────────────────┘
                      output/ + manifest.json   ← one library, shared by every project
                               │
          deliver_assets → Godot · web/three.js · Unity/Unreal/… · Tiled · any folder
```

## Why

Isometric games need *lots* of art that has to match: tiles that tile, walls whose corners meet, props with believable
lighting, characters in eight directions. Pure AI generation gives pretty single images but cannot guarantee geometry,
pivots or consistency. Pure hand modelling is slow. IsoForge splits the work by what each method is good at:

| Asset | Made by | Why |
|---|---|---|
| **Structure**: floors, walls, corners, T-junctions, doors, windows, fences, stairs, roofs, crates, barricades, towers | **Blender** kitbash, fixed camera, one light rig | Exact geometry; every piece is lit identically and shares pivots, so sets match |
| **Props, items, clutter, vegetation** | **AI sprite** (Draw Things + FLUX), background removed, quality-gated | Small perspective errors do not matter; variety does |
| **Surface textures** | **AI seamless textures** applied to Blender materials | Hand-painted look on exact geometry; tileability is checked |
| **3D props and models** | **Blender** parametric library, exported as `.glb/.fbx/.obj/.usdz` | Clean low-poly geometry, baked textures, LODs |
| **Characters** | **Blender** rigged humanoid | 8-direction sprite sheets *and* a skinned animated model |

The default art direction ("grim iso painted") is a muted, desaturated, worn look with a warm key light from the top left
and cool fill. It is a style preset (`styles/*.toml`) you can replace.

## What you get

- **2D isometric sprites and tiles** with a consistent **pivot convention: bottom vertex of the tile diamond**, in
  2:1 dimetric (default) or true isometric. Tile size is yours: 64×32, 128×64, 256×128, ...
- **Multi-tile pieces**: `footprint=[2, 2]`, `[3, 1]`, ... for slabs, long walls with several doors or windows, stairs,
  roofs. Props size themselves (a shipping container gets a [2, 3] footprint automatically).
- **A matching wall family**: `nw`, `ne`, `corner`, `end_nw`, `end_ne`, `t_nw`, `t_ne`, with door and window variants
  (open/closed), optional separate soft **ground-shadow layer**.
- **AI props** with automatic background removal (best of two models), a quality gate (coverage, single blob, no border
  contact, no halo) and automatic retries with new seeds.
- **AI seamless textures**, checked for tileability, colour-graded into one palette.
- **3D models** for any engine: baked albedo texture, LODs, per-engine axis/format presets, exact real-world heights.
- **9 parametric 3D props**: barrel, crate, shipping container, car (sedan/van/pickup, wrecked), tree (pine/round), rock,
  lamp post, fuel tank, sandbags. They also render as isometric sprites.
- **Characters**: survivor / soldier / zombie, idle/walk/attack/death, 8-direction sprite sheets, a skinned `.glb/.fbx`
  with all animations, colour and AI-texture variation.
- **Delivery adapters**: Godot 4 (TileSet, SpriteFrames, scene editing), web/three.js, generic folder with per-engine
  hints, Tiled `.tsx`. Never overwrites; conflicts get a `_v2` suffix.
- **One library for all projects**: assets live once in `output/` with a manifest (prompt, seed, style, pivot, size,
  timestamps); any project can pull from it.

## Requirements

- macOS on Apple Silicon (tested on an M1 / 16 GB). Linux/Windows are untested.
- [uv](https://docs.astral.sh/uv/) (installs Python 3.11 for you)
- [Blender](https://www.blender.org/download/) (tested on 5.2.1; other versions are untested). Auto-detected in `/Applications/Blender.app`.
- [Draw Things](https://drawthings.ai) for AI props and textures. Structures, 3D props and characters need only Blender.
- Godot 4 only if you use the Godot-specific tools.

## Install

```bash
git clone https://github.com/jafforgehq/isoforge.git
cd isoforge
./setup.sh
```

`setup.sh` creates the venv, installs dependencies, downloads the rembg models (about 1 GB, once), checks Blender and the
Draw Things API, calibrates the camera, runs the tests, and prints the exact registration command.

### Draw Things setup (for AI props and textures)

Settings → Advanced → **API Server**: on · protocol **HTTP** · port **7860** · IP **127.0.0.1** (localhost only; `0.0.0.0`
exposes your generator to the network) · TLS off. Load **FLUX.1 [schnell]** (4 steps; about 3 minutes per 1024 px image
on an M1). Large models such as Qwen-Image are far too slow on 16 GB. Draw Things must be running whenever you generate
props or textures.

### Register with your MCP client

User scope makes it available in every project:

```bash
claude mcp add isoforge --scope user -- /ABSOLUTE/PATH/isoforge/.venv/bin/python /ABSOLUTE/PATH/isoforge/server.py
```

Then reconnect (`/mcp`) or restart the client, and try `check_setup`. For other MCP clients, run
`.venv/bin/python server.py` as a stdio server.

## Using it

Just ask, in whatever project you are working in:

- *"Build a dilapidated concrete wall set and a cracked asphalt floor tile, generate a rusty oil barrel, deliver them to this project."*
- *"Generate a seamless texture of weathered brick, then build a brick wall set with it."*
- *"Make a 3×1 wall with two closed doors, with shadows."*
- *"Export a pickup truck as a Unity model: FBX and GLB, three LODs, 1.9 m tall."*
- *"Build a zombie with idle, walk, attack and death, 8 directions, and give me the Godot SpriteFrames."*
- *"Make everything for a 64×32 tile game."*

### Delivery: any engine, no setup

`deliver_assets(assets)` delivers into the project you are working in (the server's working directory) and picks the
engine: `project.godot` → Godot · `package.json` → web (`public/generated/…`, models in `public/models`) · otherwise a
generic folder. Override with `project_path=` and `type=` (`godot | web | folder | tiled`). Nothing needs registering
(`register_target` exists only as an optional shortcut).

Every non-Godot delivery includes **`isoforge_assets.json`**: file, size, pivot in pixels, pivot normalised for Unity-style
(bottom-left) and top-left origins, tile grid, camera mode, and per-engine hints (Unity, Unreal, GameMaker, Defold, Phaser).
Models list their formats, LODs, up axis, facing and units.

### Godot specifics

- `sync_to_godot` copies into `assets/generated/{tiles,sprites,models}`, then runs a headless import.
- `build_tileset(set, assets)` packs floors and walls into atlases and writes an isometric `TileSet`
  (`tile_shape = Isometric`, `tile_layout = Diamond Down`, `tile_size = 128×64`, pivots baked into `texture_origin`).
  Use `TileMapLayer`, and enable **Y Sort** on the layers and their parent. Per-piece atlas coordinates are written to
  `<set>.tiles.json`. Multi-tile pieces are rejected here (a TileMap cell holds one tile); place them as sprites.
- `place_in_scene(scene, asset, x, y, parent, node_name)` edits the `.tscn` text: unique `ext_resource`, node inserted
  before `[connection]`/`[editable]`, one-time `.bak`, `position` = the sprite's bottom-centre (offset baked), idempotent.
  **Reload the scene in the editor afterwards.**
- `make_scene(asset, footprint=true)` writes a reusable scene (Node2D → Sprite2D, optional diamond collision).
- `build_spriteframes(character)` writes a `SpriteFrames` with animations like `walk_SW`.

## Tool reference

| Tool | What it does |
|---|---|
| `check_setup` | What is installed/running; calibrated profiles; style |
| `list_kinds` | Everything buildable: structures, 3D props, characters, materials, engines |
| `list_styles` / `set_style` | Style presets; lock one for all new assets |
| `calibrate` | Calibrate the camera for a tile size / camera mode (cached per size) |
| `generate_asset` | AI prop sprite (background job) |
| `generate_texture` | AI seamless texture (background job) |
| `build_floor_tile` / `build_wall_set` / `build_door` / `build_window` / `build_structure` | Blender structures as iso sprites |
| `build_model` | Any piece or 3D prop as `.glb/.fbx/.obj/.usdz`, LODs, baked texture |
| `build_character` | Rigged humanoid: 8-direction sheets and/or animated model (background job) |
| `resize_asset` | Resized copy of a sprite, tile or whole character |
| `regenerate` / `delete_asset` | Redo an asset / delete (needs `confirm=true`) |
| `list_assets` | The library |
| `deliver_assets` / `export_to_folder` / `register_target` / `list_targets` | Deliver to any engine |
| `sync_to_godot` / `build_tileset` / `place_in_scene` / `make_scene` / `build_spriteframes` | Godot 4 |
| `job_status` | Poll a background job |
| `generate_from_mesh` / `render_mesh` | Optional image-to-3D (not installed; returns instructions) |

Slow tools (`generate_*`, `build_character`) return a `job_id`; poll `job_status(job_id, wait_seconds=60)` so a
three-minute generation never hits a client timeout. Jobs that run across a server restart report `lost` and are safe to
re-run (everything is idempotent).

### Materials, pieces and presets

- Materials: `concrete`, `asphalt`, `brick`, `rust`, `wood`, or any AI texture via `texture=`.
- Structure pieces: `floor`, `wall_nw|ne|corner|end_nw|end_ne|t_nw|t_ne`, `door`, `window`, `fence`, `stairs`, `roof`, `crate`, `barricade`, `tower`.
- 3D props: `prop_barrel`, `prop_crate3d`, `prop_container`, `prop_car` (variant `sedan|van|pickup`, `wrecked`), `prop_tree` (variant `pine|round`), `prop_rock`, `prop_lamp_post`, `prop_fuel_tank`, `prop_sandbags`.
- Characters: presets `survivor | soldier | zombie`; animations `idle | walk | attack | death`; directions `S, SW, W, NW, N, NE, E, SE`.
- Engine presets for models: `three | unity | godot | unreal | blender | generic`.

## Sizes: per call, per game

Nothing size-related is global. Every Blender and sprite tool accepts
`layout={tile_w, tile_h, camera_mode, wall_height_px, sprite_max_px}` that applies to that call only, so different games
(or parallel sessions) never interfere. Unspecified values follow `tile_w`: `tile_h` from the camera (2:1 → `tile_w/2`,
isometric → `tile_w × 0.577`), wall height and sprite size proportionally. Each size is calibrated once and cached side by side.

| Need | Knob |
|---|---|
| Tile grid (64×32, 128×64, 256×128, true isometric) | `layout={"tile_w": 64}` or `{"camera_mode": "isometric"}` |
| Multi-tile pieces | `footprint=[fx, fy]` (whole tiles, 1–12) on floor, walls, door, window, fence, stairs, roof |
| Wall / structure height | `layout.wall_height_px`, `build_wall_set(height=)`, piece params (`height_px`, `steps`, `count`) |
| Prop sprite size | `generate_asset(max_px=)`; generation resolution `gen_size` (512/768/1024) |
| Existing asset at another size | `resize_asset(asset, max_px= or scale=, mode=smooth|pixel)` |
| 3D model real-world size | `build_model(height_m=, scale=, meters_per_tile=)`, `lods=[3000, 800, 250]`, `texture_size` |
| Character size | `build_character(height_m=, meters_per_tile=, layout=)` |

`calibrate(..., make_default=true)` saves a default instead of passing `layout` each time.

## Style locking

`styles/<name>.toml` holds the prompt prefix, steps, size, post mode (`smooth | pixel`), palette size, texture prefix and
saturation. `set_style(name)` locks one for all new assets (saved in `output/state.json`); existing assets keep their
recorded style and `regenerate(asset)` redoes one. Use descriptive terms in prompts, never game names. A `pixel` post
mode (nearest-neighbour + palette reduction) is available for pixel-art looks.

## How it works

- **Calibration.** A 1×1 floor tile is rendered with the shared orthographic rig and its sub-pixel area is measured;
  the camera scale is tuned until the diamond equals `tile_w × tile_h`. Cached per (size, camera).
- **Pivots.** Every sprite's pivot is the bottom vertex of its footprint diamond. Square footprints are cropped
  symmetrically so the pivot is exactly `(w/2, h)` for a whole family; rectangular footprints are cropped tightly and the
  real pivot is recorded.
- **Props.** prompt = style prefix + subject → FLUX → rembg with two models (kept by alpha-quality score) → defringe →
  quality gate, retry up to 3× with a new seed → trim, resize, even-pad → PNG + sidecar JSON + manifest.
- **Textures.** Generate → seam check (wrap seam vs. interior neighbour difference) → offset-blend fix only if needed →
  grade into the palette → applied to Blender materials by box projection.
- **Models.** Built in tile units, scaled to metres, decimated per LOD, UV-unwrapped and baked (Cycles) to a single
  albedo image, rotated so the model faces the requested axis, exported.
- **Memory.** On 16 GB, image generation and Blender never run together: a cross-process lock queues heavy jobs, also
  across several MCP sessions sharing one library.
- **Safety.** Writes go only to `output/`, the target project's asset folders, and the `.tscn`/`.tres` you name; paths
  are validated against traversal; subprocesses have timeouts; the manifest is written atomically under a file lock.

## Repository layout

```
server.py            MCP server (stdio)
isoforge/            package: config, manifest, postprocess, blender driver, characters, textures, resize,
                     godot, export, targets, jobs, backends/drawthings
blender/             scripts that run inside Blender: scene_rig, kitbash, props3d, character,
                     render_iso, render_anim, export_models, calibrate
styles/              style presets          tests/   pytest suite        smoke/   end-to-end acceptance scripts
output/              generated library (git-ignored): raw, textures, sprites, tiles, meshes, renders, manifest.json
```

## Limits (honest list)

- Characters are blocky, rigid-skinned humanoids (about 70 px tall at 2 m per tile; use `meters_per_tile` for bigger).
  No LODs for characters (decimation would break skin weights).
- Walls cover the two back sides the camera looks into. Very long shadows can be clipped at the sprite edge.
- Model textures are baked albedo only (no normal/roughness maps).
- AI props are generated at 512–1024 px; much larger sprites would be upscaled and soft. Resizing Blender tiles gives soft
  diamonds, so re-render with `layout` instead.
- The isometric-view check of AI sprites is flagged `iso_check: skipped` (no reliable cheap heuristic); review props visually.
- Only the Godot adapter was verified inside the actual engine. The web, folder and Tiled outputs are tested for structure
  but not opened in those tools.
- Image-to-3D (TripoSR) is intentionally not included. `generate_from_mesh` and `render_mesh` return a clear message.
- Tested on macOS/Apple Silicon only.

## Development

```bash
.venv/bin/python -m pytest -q tests      # calibration, quality gates, tileability, .tscn editing, exports, sizes, server over stdio
.venv/bin/python smoke/acceptance.py     # full 2D flow into a brand-new Godot project (needs Draw Things for the barrel)
.venv/bin/python smoke/acceptance_3d.py  # models, characters, SpriteFrames loaded by Godot itself
```

Logs: `output/isoforge.log`. Everything is idempotent: re-running an identical request returns the existing asset.

## Credits and licences

IsoForge is MIT-licensed (see `LICENSE`). It orchestrates other software, each under its own terms: Blender (GPL),
[Draw Things](https://drawthings.ai), [rembg](https://github.com/danielgatis/rembg) and its models, Pillow, NumPy, SciPy and
the MCP Python SDK. **Generated assets are subject to the licence of the image model you load** (for example FLUX.1
[schnell] is Apache-2.0); check your model's terms before shipping assets commercially.
