#!/usr/bin/env bash
# Поднять окружение песочницы Arena одной командой после её сброса.
#
#   tools/sandbox/bootstrap.sh            # всё нужное: Godot + импортёр + медиа
#   tools/sandbox/bootstrap.sh --check    # только проверить, что уже есть
#
# Качается только то, чего нет: /tmp чистится между сессиями, поэтому каждый
# шаг сначала смотрит на диск. Все источники — из белого списка песочницы
# (api.github.com, pypi.org, files.pythonhosted.org); download.blender.org
# недоступен, поэтому Blender ставится pip-модулем bpy, а X11/GL-зависимости
# закрываются пустыми стабами (см. bpy_stubs.py).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
WORK="${ARENA_WORK:-/tmp}"
CHECK=0
for a in "$@"; do
  case "$a" in
    --check) CHECK=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "неизвестный параметр: $a" >&2; exit 2 ;;
  esac
done

say() { echo "==> $*"; }
ok()  { echo "    ✓ $*"; }
miss(){ echo "    ✗ $*"; }

# ---------------------------------------------------------------- Godot 4.7.2
# Берётся из Creative36711/synapse (tools/godot/dist): xz-куски бинарника и
# SwiftShader. Это единственный известный источник, у которого рендер работает
# без GPU: offscreen + Vulkan на CPU.
SYNAPSE_REPO="Creative36711/synapse"
GODOT_DIR="$WORK/godotbin"
GODOT_BIN="$GODOT_DIR/godot"

gh_blob() { # <repo> <path> <dest>
  local repo="$1" path="$2" dest="$3" sha
  sha=$(curl -sS "https://api.github.com/repos/$repo/contents/$path" \
        -H "Accept: application/vnd.github+json" \
        | python3 -c 'import json,sys; print(json.load(sys.stdin)["sha"])')
  curl -sS -L "https://api.github.com/repos/$repo/git/blobs/$sha" \
    -H "Accept: application/vnd.github.raw" -o "$dest"
}

install_godot() {
  if [ -x "$GODOT_BIN" ]; then ok "Godot уже есть: $($GODOT_BIN --version 2>/dev/null | tail -1)"; return; fi
  [ "$CHECK" = 1 ] && { miss "Godot нет ($GODOT_BIN)"; return; }
  mkdir -p "$GODOT_DIR"
  say "Godot 4.7.2 + SwiftShader (~66 МБ)"
  local base="tools/godot/dist"
  gh_blob "$SYNAPSE_REPO" "$base/SHA256SUMS" "$GODOT_DIR/SHA256SUMS"
  for part in 00 01; do
    gh_blob "$SYNAPSE_REPO" "$base/godot-linux-x86_64.xz.part-$part" "$GODOT_DIR/part-$part"
    echo "    скачан кусок $part"
  done
  # Имена в SHA256SUMS длинные, у нас файлы короткие — сверяем по парам
  # «ожидаемый хеш ↔ наш файл», а не подменой имён в sed.
  local want0 want1
  want0=$(grep 'part-00' "$GODOT_DIR/SHA256SUMS" | cut -d' ' -f1)
  want1=$(grep 'part-01' "$GODOT_DIR/SHA256SUMS" | cut -d' ' -f1)
  echo "$want0  $GODOT_DIR/part-00" | sha256sum -c -
  echo "$want1  $GODOT_DIR/part-01" | sha256sum -c -
  cat "$GODOT_DIR"/part-* > "$GODOT_DIR/g.xz"
  xz -dc "$GODOT_DIR/g.xz" > "$GODOT_BIN"
  chmod +x "$GODOT_BIN"
  local want
  want=$(grep 'godot (uncompressed)' "$GODOT_DIR/SHA256SUMS" | cut -d' ' -f1)
  echo "$want  $GODOT_BIN" | sha256sum -c -
  gh_blob "$SYNAPSE_REPO" "$base/swiftshader-linux-x86_64.tar.xz" "$GODOT_DIR/sw.tar.xz"
  tar -xf "$GODOT_DIR/sw.tar.xz" -C "$GODOT_DIR"
  rm -f "$GODOT_DIR"/part-* "$GODOT_DIR/g.xz" "$GODOT_DIR/sw.tar.xz" "$GODOT_DIR/sums.txt"
  ok "Godot: $($GODOT_BIN --version | tail -1)"
}

# Запуск Godot с рендером на CPU (SwiftShader). Без этих переменных движок
# падает на «could not initialize the Vulkan context».
godot_run() {
  VK_ICD_FILENAMES="$GODOT_DIR/vk_swiftshader_icd.json" \
  LD_LIBRARY_PATH="$GODOT_DIR:${LD_LIBRARY_PATH:-}" \
  "$GODOT_BIN" "$@"
}

# ------------------------------------------------------------- Blender (bpy)
# download.blender.org в песочнице недоступен, зато pypi.org открыт:
# bpy==4.5.3 — это целый Blender 4.5.3 LTS как pip-модуль. Колесо требует
# CPython 3.11 и линкуется с X11/GL, которых в песочнице нет — стабы
# закрывают линковку, рендер идёт через Cycles на CPU.
BPY_VERSION="${BPY_VERSION:-4.5.3}"
install_bpy() {
  local venv="$WORK/bpyenv" stubs="$WORK/bpystubs"
  if [ -x "$venv/bin/python" ] && [ -f "$stubs/USE" ] \
     && LD_LIBRARY_PATH="$stubs" "$venv/bin/python" -c 'import bpy' 2>/dev/null; then
    ok "Blender уже есть: $(LD_LIBRARY_PATH="$stubs" "$venv/bin/python" -c 'import bpy; print(bpy.app.version_string)')"; return
  fi
  [ "$CHECK" = 1 ] && { miss "нет bpy в $venv"; return; }
  command -v python3.11 >/dev/null || { miss "нужен python3.11 (bpy 4.5.x только под cp311)"; return; }
  say "Blender $BPY_VERSION как модуль bpy (~355 МБ, один раз)"
  python3.11 -m venv "$venv"
  "$venv/bin/pip" -q install --disable-pip-version-check "bpy==$BPY_VERSION"
  local pkg
  pkg=$(ls -d "$venv"/lib/python*/site-packages/bpy | head -1)
  mkdir -p "$stubs"
  python3.11 "$HERE/bpy_stubs.py" "$pkg" "$stubs" >/dev/null
  LD_LIBRARY_PATH="$stubs" "$venv/bin/python" -c 'import bpy; print("    Blender", bpy.app.version_string)'
  ok "bpy готов; запуск: LD_LIBRARY_PATH=$stubs $venv/bin/python"
}

# ---------------------------------------------------------------- Медиа (Pillow)
install_media() {
  local venv="$WORK/mediaenv"
  if [ -x "$venv/bin/python" ] && "$venv/bin/python" -c 'import PIL' 2>/dev/null; then
    ok "медиа-окружение уже есть: $venv"; return
  fi
  [ "$CHECK" = 1 ] && { miss "нет медиа-окружения: $venv"; return; }
  say "Медиа-окружение (хромакей)"
  python3 -m venv "$venv"
  "$venv/bin/pip" -q install --disable-pip-version-check Pillow numpy
  ok "готово"
}

install_godot
install_media
install_bpy

cat <<EOF

Готово. Дальше:
  Godot:     godot_run --version
  хромакей:  $WORK/mediaenv/bin/python $HERE/cutout_chromakey.py in.png out.png --crop
EOF
