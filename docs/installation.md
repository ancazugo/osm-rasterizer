# Installation

Requires Python 3.12+.

## From PyPI

```bash
pip install osm-rasterizer
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv add osm-rasterizer        # as a project dependency
uv tool install osm-rasterizer  # as a standalone CLI tool
```

## From source

```bash
git clone https://github.com/ancazugo/osm-rasterizer
cd osm-rasterizer
uv sync
```

## Development

```bash
# Run tests (unit tests only, no network)
uv run pytest

# Run including integration tests (requires Overpass network access)
uv run pytest -m integration
```
