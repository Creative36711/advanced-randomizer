#!/usr/bin/env bash
# Собрать GDExtension OpenBFME из upstream/ — одной командой, с обходом
# известных дефектов сборки на строгом GCC.
#
#   tools/sandbox/build_engine.sh              # собрать (долго: 15+ мин на 2 ядрах)
#   tools/sandbox/build_engine.sh --check      # что уже собрано
#   tools/sandbox/build_engine.sh --core       # только ядро: 879 целей, 17 мин (замерено)
#   tools/sandbox/build_engine.sh --quick      # ядро без 675 тестовых файлов, повторная сборка — секунды
#   tools/sandbox/build_engine.sh --clean      # снести сборку и собрать заново
#
# ЧТО ЗДЕСЬ ВАЖНО (проверено на практике):
#  1. engine/thirdparty/godot-cpp — ПУСТОЙ сабмодуль. Скрипт скачивает его
#     по пину из upstream (codeload; release-assets недоступен в песочнице).
#  2. 185 заголовков upstream используют size_t без <cstddef>; GCC 12 на этом
#     падает. Один флаг -include cstddef закрывает все.
#  3. Сборка идёт ~2 минуты на конфигурацию и 15+ минут на ядро при -j2.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
SRC="$REPO/upstream"
BUILD="$SRC/engine/build"
GODOTCPP_REV="507ed9d840c01a3c5b2a39af8bb4000bfac30bf5"   # пин из upstream
PATH="/tmp/buildenv/bin:$PATH"

say()  { printf '==> %s\n' "$*"; }
ok()   { printf '    ✓ %s\n' "$*"; }
die()  { printf 'ОШИБКА: %s\n' "$*" >&2; exit 1; }

MODE="build"
case "${1:-}" in
  --check) MODE="check" ;;
  --core)  MODE="core" ;;
  --quick) MODE="quick" ;;
  --clean) MODE="clean" ;;
  "")      ;;
  *) die "неизвестный аргумент: $1" ;;
esac

# ------------------------------------------------------------------ проверки
command -v cmake >/dev/null || die "нет cmake — запустите tools/sandbox/bootstrap.sh"
command -v ninja >/dev/null || die "нет ninja — запустите tools/sandbox/bootstrap.sh"
[ -d "$SRC/engine" ] || die "нет $SRC/engine — снимок upstream не распакован"

if [ "$MODE" = "check" ]; then
  echo "источник:  $SRC"
  [ -d "$SRC/engine/thirdparty/godot-cpp/src" ] && ok "godot-cpp на месте" || echo "    ✗ godot-cpp не скачан"
  [ -f "$BUILD/libopenbfme_core.a" ] && ok "ядро: $(du -h "$BUILD/libopenbfme_core.a" | cut -f1)" || echo "    ✗ ядро не собрано"
  lib=$(find "$SRC/godot/bin" -name 'libopenbfme.so' -o -name 'openbfme.linux*' 2>/dev/null | head -1)
  [ -n "$lib" ] && ok "расширение: $lib" || echo "    ✗ расширение не собрано"
  exit 0
fi

# ------------------------------------------------------- godot-cpp по пину
if [ ! -d "$SRC/engine/thirdparty/godot-cpp/src" ]; then
  [ "$MODE" = "check" ] && die "godot-cpp не скачан"
  say "godot-cpp $GODOTCPP_REV (~34 МБ)"
  tmp=$(mktemp -d)
  curl -sSL "https://codeload.github.com/godotengine/godot-cpp/zip/$GODOTCPP_REV" -o "$tmp/gcpp.zip" \
    || die "не скачался godot-cpp"
  unzip -q "$tmp/gcpp.zip" -d "$tmp/x" || die "не распаковался godot-cpp"
  rm -rf "$SRC/engine/thirdparty/godot-cpp"
  mv "$tmp"/x/*/ "$SRC/engine/thirdparty/godot-cpp" || die "не удалось положить godot-cpp"
  rm -rf "$tmp"
  ok "godot-cpp на месте"
fi

# ------------------------------------------------------------ конфигурация
GODOT_FLAG=ON
[ "$MODE" = "core" ] && GODOT_FLAG=OFF
# --quick: the same as --core, plus no test executable. 675 test files are two thirds of the 2686 targets, and an edit inside a header rebuilds
# them all: the code loop does not need them (run the tests of the CI build instead)
TESTS_FLAG=ON
[ "$MODE" = "quick" ] && { GODOT_FLAG=OFF; TESTS_FLAG=OFF; }

if [ "$MODE" = "clean" ]; then
  say "снести $BUILD"
  rm -rf "$BUILD"
fi

mkdir -p "$BUILD"
say "конфигурация (GODOT=$GODOT_FLAG)"
cmake -S "$SRC/engine" -B "$BUILD" -G Ninja \
      -DCMAKE_BUILD_TYPE=Release \
      -DOPENBFME_BUILD_GODOT="$GODOT_FLAG" \
      -DCMAKE_CXX_FLAGS="-include cstddef" \
      -DOPENBFME_BUILD_TESTS="$TESTS_FLAG" \
      > "$BUILD/configure.log" 2>&1 || { tail -20 "$BUILD/configure.log"; die "конфигурация не прошла"; }
ok "конфигурация готова"

# ------------------------------------------------------------------ сборка
TARGET=openbfme
[ "$MODE" = "core" ] && TARGET=openbfme_core
[ "$MODE" = "quick" ] && TARGET=openbfme_peer

# the measured numbers (2 cores): --quick first build 17 min / 879 targets, --core 17 min, full 28 min / 2686 targets; after an edit of ONE .cpp
# the same build takes 16 s, and almost all of it is the link, not the compile (a header parse is 1.8 s of a 1.9 s object)
say "сборка $TARGET (-j$(nproc); первый раз это долго, потом секунды)"
start=$(date +%s)
ninja -C "$BUILD" "$TARGET" -j"$(nproc)" > "$BUILD/build.log" 2>&1
rc=$?
end=$(date +%s)
printf '    время: %d мин %d с\n' $(( (end-start)/60 )) $(( (end-start)%60 ))

if [ $rc -ne 0 ]; then
  echo "--- ошибки:"
  grep -m10 'error:' "$BUILD/build.log" || tail -20 "$BUILD/build.log"
  die "сборка не прошла, полный лог: $BUILD/build.log"
fi

ok "собрано: $TARGET"
if [ "$MODE" != "core" ]; then
  find "$SRC/godot/bin" -name '*.so' 2>/dev/null | while read -r f; do
    printf '    расширение: %s (%s)\n' "$f" "$(du -h "$f" | cut -f1)"
  done
fi
