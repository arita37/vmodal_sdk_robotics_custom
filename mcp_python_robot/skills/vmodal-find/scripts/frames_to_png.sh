#!/usr/bin/env bash
help='
  Convert VModal frames (WebP, sometimes saved with a .jpg name) to PNG so they can be viewed.
  Prints one line per input: the PNG path, or "FAIL <input>".
  Relative inputs are resolved against $VMODAL_MCP_CWD, the current dir, then $HOME
  (the MCP server saves ztmp/vmodal/... relative to its own working directory).
  Converters tried in order: sips (macOS), dwebp, ffmpeg, magick/convert.

  frames_to_png.sh <out_dir> <frame>...                      # default: imgs_to_png
  frames_to_png.sh imgs_to_png /tmp/vmodal-find ztmp/vmodal/20261006_131804/city/a.webp
  frames_to_png.sh os_resolve ztmp/vmodal/20261006_131804/city/a.webp
'

os_resolve() {
  local help='
    ## Usage:
      frames_to_png.sh os_resolve ztmp/vmodal/20261006_131804/city/a.webp
  '
  local p="$1" base
  if [[ "$p" == /* ]]; then [[ -f "$p" ]] && echo "$p" && return 0; return 1; fi
  for base in "${VMODAL_MCP_CWD:-}" "$PWD" "$HOME"; do
    [[ -n "$base" && -f "$base/$p" ]] && echo "$base/$p" && return 0
  done
  return 1
}

img_to_png() {
  local help='
    ## Usage:
      frames_to_png.sh img_to_png ~/ztmp/vmodal/x/city/a.webp /tmp/vmodal-find/a.png
  '
  local src="$1" dst="$2"
  if command -v sips >/dev/null; then sips -s format png "$src" --out "$dst" >/dev/null 2>&1 && return 0; fi
  if command -v dwebp >/dev/null; then dwebp -quiet "$src" -o "$dst" 2>/dev/null && return 0; fi
  if command -v ffmpeg >/dev/null; then ffmpeg -loglevel error -y -i "$src" "$dst" && return 0; fi
  if command -v magick >/dev/null; then magick "$src" "$dst" && return 0; fi
  if command -v convert >/dev/null; then convert "$src" "$dst" && return 0; fi
  return 1
}

imgs_to_png() {
  local help='
    ## Usage:
      frames_to_png.sh imgs_to_png /tmp/vmodal-find ztmp/vmodal/x/city/a.webp ztmp/vmodal/x/city/b.jpg
  '
  local out="$1" p src dst
  shift
  mkdir -p "$out"
  for p in "$@"; do
    src=$(os_resolve "$p") || { echo "FAIL $p"; continue; }
    dst="$out/$(basename "${src%.*}").png"
    img_to_png "$src" "$dst" && echo "$dst" || echo "FAIL $p"
  done
}

case "${1:-}" in
  ""|-h|--help|help) echo "$help" ;;
  os_resolve|img_to_png|imgs_to_png) "$@" ;;
  *) imgs_to_png "$@" ;;
esac
