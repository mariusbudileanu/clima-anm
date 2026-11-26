#!/usr/bin/env bash
# Clima ANM — pornire pe Linux / macOS. La prima rulare descarcă pixi și instalează mediul portabil.
set -euo pipefail
cd "$(dirname "$0")"
V=0.84.2
export PIXI_HOME="$PWD/instrumente/pixi_home" PIXI_CACHE_DIR="$PWD/.pixi/cache"
PIXI="$PWD/instrumente/pixi"
if [ ! -x "$PIXI" ]; then
  case "$(uname -s)-$(uname -m)" in
    Linux-x86_64)  A=pixi-x86_64-unknown-linux-musl.tar.gz; S=6d2a576bde0a7b26533a068fec0aea6e4ee21c36668efc1dc73fce90110906ae ;;
    Darwin-arm64)  A=pixi-aarch64-apple-darwin.tar.gz;      S=039d4b48c7e17bc62a36faa2af1b13d0d187f5dd6e8fea17e0587302438df6e6 ;;
    Darwin-x86_64) A=pixi-x86_64-apple-darwin.tar.gz;       S=a633a4f8276955b73248397c17ce77380eb7133dc96c54bc271239b7dc9b8837 ;;
    *) echo "Platformă nesuportată: $(uname -s) $(uname -m)"; exit 1 ;;
  esac
  echo "Prima pornire: descarc pixi $V…"
  mkdir -p instrumente && curl -fsSL -o "instrumente/$A" "https://github.com/prefix-dev/pixi/releases/download/v$V/$A"
  H=$( (sha256sum "instrumente/$A" 2>/dev/null || shasum -a 256 "instrumente/$A") | cut -d' ' -f1)
  [ "$H" = "$S" ] || { echo "SHA256 greșit pentru $A"; rm -f "instrumente/$A"; exit 1; }
  tar -xzf "instrumente/$A" -C instrumente && rm "instrumente/$A" && chmod +x "$PIXI"
fi
if [ ! -x .pixi/envs/default/bin/python ]; then
  # ~1 GB mediul + ~0,7 GB arhivele descărcate (șterse la final); pe exFAT/FAT32 (stick USB) aproape dublu
  LIBER=$(df -Pk . 2>/dev/null | awk 'NR==2{print int($4/1048576*10)/10}')
  FS=$(df -PT . 2>/dev/null | awk 'NR==2{print $2}')
  case "$FS" in *fat*|*FAT*|msdos) NEVOIE=3.5; echo "Atenție: discul este $FS (stick USB?): instalarea ocupă ~3 GB.";; *) NEVOIE=2.0;; esac
  if [ -n "$LIBER" ] && awk "BEGIN{exit !($LIBER < $NEVOIE)}"; then
    echo "Spațiu insuficient: $LIBER GB liberi, sunt necesari ~$NEVOIE GB. Eliberați spațiu sau mutați folderul."; exit 1
  fi
  echo "Instalez mediul de lucru (~1 GB, o singură dată)…"
  "$PIXI" install --locked --manifest-path "$PWD/pixi.toml" || { echo "Instalarea a eșuat (internet / proxy?). Reporniți scriptul."; exit 1; }
  "$PIXI" clean cache --conda --yes >/dev/null 2>&1 || true     # arhivele descărcate nu mai sunt necesare
fi
exec "$PIXI" run --locked --manifest-path "$PWD/pixi.toml" interfata
