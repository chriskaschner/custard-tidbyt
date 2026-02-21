# Culver's Flavor of the Day - Tidbyt App

A Tidbyt community app that displays a 3-day forecast of Culver's Flavor of the Day custard flavors with color-coded ice cream cone icons.

![Flavor forecast example](apps/culversfotd/example.gif)

## Features

- 3-day flavor forecast with mini ice cream cone icons
- 29 flavor profiles with unique color-coded scoops, ribbons, and toppings
- Search for any of 1,000+ Culver's locations via typeahead
- Scrolling marquee header for long location names
- Two-tier cache for resilient offline rendering
- Staggered cone layout optimized for the 64x32 pixel Tidbyt display

## Setup

Search for "Culver's FOTD" in the Tidbyt mobile app, then use the store selector to pick your nearest Culver's location.

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
Tidbyt Mobile App                  Cloudflare Worker
┌─────────────────┐               ┌──────────────────────────────────┐
│ schema.Typeahead │──search──────>│ GET /api/stores?q=...            │
│ (store selector) │               │   (in-memory substring search)   │
└─────────────────┘               └──────────────────────────────────┘

Tidbyt Device (every ~15 min)     Cloudflare Worker
┌─────────────────┐               ┌──────────────────────────────────┐
│ main(config)    │──fetch───────>│ GET /api/flavors?slug=mt-horeb   │
│ cache miss?     │               │   (KV-cached Culver's scrape)    │
│ render 3 cones  │<──JSON────────│                                  │
└─────────────────┘               └──────────────────────────────────┘
```

Data is fetched from the [custard-calendar](https://github.com/chriskaschner/custard-calendar) Cloudflare Worker API.

## Repo Structure

```
apps/culversfotd/
├── culvers_fotd.star    # The app (~500 lines)
└── manifest.yaml        # Community app metadata
```

This mirrors `tidbyt/community` layout so submission is a direct copy of `apps/culversfotd/`.
