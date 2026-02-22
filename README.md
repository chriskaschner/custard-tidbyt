# Custard Flavor of the Day - Tidbyt App

A Tidbyt community app that displays a 3-day forecast of Flavor of the Day custard flavors with color-coded ice cream cone icons. Supports Culver's, Kopp's, Gille's, Hefner's, Kraverz, and Oscar's.

![Flavor forecast example](apps/culversfotd/example.gif)

## Features

- 3-day flavor forecast with mini ice cream cone icons
- 6 brands across 1,079 stores with auto-detected brand theming
- 29 flavor profiles with unique color-coded scoops, ribbons, and toppings
- Contrast-safe header text (black text on light brand colors)
- Scrolling marquee header for long location names
- Two-tier cache for resilient offline rendering
- Staggered cone layout optimized for the 64x32 pixel Tidbyt display

### Brand Theming

| Brand | Header Color | Text |
|-------|-------------|------|
| Culver's | Navy (#003366) | White |
| Kopp's | Black (#000000) | White |
| Gille's | Yellow (#EBCC35) | Black |
| Hefner's | Green (#93BE46) | Black |
| Kraverz | Orange (#CE742D) | White |
| Oscar's | Red (#BC272C) | White |

Brand is auto-detected from the store slug — no extra configuration needed.

## Flavor Name Abbreviations

Flavor names are compressed to fit the 64-pixel display width (max 5 characters per line, 2 lines per column). The display shows the abbreviated name split across two lines separated by `/` below:

| Full Flavor Name | Display |
|---|---|
| Andes Mint Avalanche | `Mint / Avlnc` |
| Butter Pecan | `Buttr / Pecan` |
| Caramel Cashew | `Crml / Cashw` |
| Caramel Chocolate Pecan | `Crml / Pecan` |
| Caramel Fudge Cookie Dough | `Fudge / Dough` |
| Caramel Peanut Buttercup | `PB / Dove` |
| Caramel Pecan | `Crml / Pecan` |
| Caramel Turtle | `Crml / Turtl` |
| Chocolate Caramel Twist | `Crml / Twist` |
| Chocolate Covered Strawberry | `Choc / Straw` |
| Chocolate Heath Crunch | `Heath / Crunc` |
| Chocolate Volcano | `Choc / Volc` |
| Crazy for Cookie Dough | `Crazy4 / Dough` |
| Dark Chocolate Decadence | `Choc / Decad` |
| Dark Chocolate PB Crunch | `DK PB / Crunc` |
| Devil's Food Cake | `Devil / Cake` |
| Double Strawberry | `Dbl / Straw` |
| Georgia Peach | `GA / Peach` |
| Mint Cookie | `Mint / Cook` |
| Mint Explosion | `Mint / Expl` |
| OREO Cookie Cheesecake | `Oreo / Chees` |
| OREO Cookie Overload | `Oreo / Cook` |
| Raspberry Cheesecake | `Rasp / Chees` |
| Really Reese's | `Reese` |
| Salted Double Caramel Pecan | `Salt / Pecan` |
| Snickers Swirl | `Snkrs / Swirl` |
| Turtle | `Turtl` |
| Turtle Cheesecake | `Turtl / Chees` |
| Turtle Dove | `Turtl / Dove` |

Unknown flavors use an abbreviation map + base-noun anchoring to auto-compress (e.g. "Chocolate" -> "Choc", "Caramel" -> "Crml").

## Setup

Search for "Custard FOTD" in the Tidbyt mobile app, then use the store selector to pick your nearest location.

## Development

### Prerequisites

- [Pixlet](https://github.com/tidbyt/pixlet) (`brew install tidbyt/tidbyt/pixlet`)

### Commands

```bash
# Lint / check for errors
pixlet check apps/culversfotd/culvers_fotd.star

# Render to WebP
pixlet render apps/culversfotd/culvers_fotd.star

# Serve with live preview at http://localhost:8080
pixlet serve apps/culversfotd/culvers_fotd.star
```

## Architecture

```
Tidbyt Mobile App                  Cloudflare Worker (v1 API)
┌─────────────────┐               ┌──────────────────────────────────┐
│ schema.Typeahead │──search──────>│ GET /api/v1/stores?q=...         │
│ (store selector) │               │   (1,079 stores, 6 brands)      │
└─────────────────┘               └──────────────────────────────────┘

Tidbyt Device (every ~15 min)     Cloudflare Worker (v1 API)
┌─────────────────┐               ┌──────────────────────────────────┐
│ main(config)    │──fetch───────>│ GET /api/v1/flavors?slug=mt-horeb│
│ brand_from_slug │               │   (KV-cached, multi-brand)       │
│ render 3 cones  │<──JSON────────│                                  │
└─────────────────┘               └──────────────────────────────────┘
```

Data is fetched from the [custard-calendar](https://github.com/chriskaschner/custard-calendar) Cloudflare Worker API.

## Repo Structure

```
apps/culversfotd/
├── culvers_fotd.star    # The app (~950 lines)
└── manifest.yaml        # Community app metadata
scripts/
└── backfill_custard.py  # Store discovery and flavor backfill tool
```

This mirrors `tidbyt/community` layout so submission is a direct copy of `apps/culversfotd/`.
