#!/usr/bin/env bash
# External tools m3talist shells out to.
#   ffmpeg/ffprobe - required, transcoding and probing
#   fpcalc         - optional, duplicate detection only
set -euo pipefail

FFMPEG_HINT=""
FPCALC_HINT=""
INSTALL_CMD=""

detect() {
    case "$(uname -s)" in
        Darwin)
            INSTALL_CMD="brew install ffmpeg chromaprint"
            FFMPEG_HINT="brew install ffmpeg"
            FPCALC_HINT="brew install chromaprint"
            ;;
        Linux)
            if command -v dnf >/dev/null; then
                # ffmpeg-free ships in the main repos; the full ffmpeg needs RPM Fusion.
                INSTALL_CMD="sudo dnf install -y ffmpeg-free chromaprint-tools"
                FFMPEG_HINT="sudo dnf install ffmpeg-free   # or ffmpeg from RPM Fusion"
                FPCALC_HINT="sudo dnf install chromaprint-tools"
            elif command -v apt-get >/dev/null; then
                # Debian, Ubuntu, Mint, Pop!_OS
                INSTALL_CMD="sudo apt-get install -y ffmpeg libchromaprint-tools"
                FFMPEG_HINT="sudo apt install ffmpeg"
                FPCALC_HINT="sudo apt install libchromaprint-tools"
            elif command -v pacman >/dev/null; then
                INSTALL_CMD="sudo pacman -S --needed ffmpeg chromaprint"
                FFMPEG_HINT="sudo pacman -S ffmpeg"
                FPCALC_HINT="sudo pacman -S chromaprint"
            elif command -v zypper >/dev/null; then
                INSTALL_CMD="sudo zypper install -y ffmpeg chromaprint-fpcalc"
                FFMPEG_HINT="sudo zypper install ffmpeg"
                FPCALC_HINT="sudo zypper install chromaprint-fpcalc"
            fi
            ;;
        MINGW*|MSYS*|CYGWIN*)
            FFMPEG_HINT="winget install Gyan.FFmpeg"
            FPCALC_HINT="download fpcalc from https://acoustid.org/chromaprint and put it on PATH"
            ;;
    esac
}

report() {
    local missing=0
    for tool in ffmpeg ffprobe; do
        if command -v "$tool" >/dev/null; then
            printf '  [ok]      %s\n' "$tool"
        else
            printf '  [MISSING] %s  (required)\n' "$tool"
            missing=1
        fi
    done
    if command -v fpcalc >/dev/null; then
        printf '  [ok]      fpcalc\n'
    else
        printf '  [absent]  fpcalc  (optional: duplicate detection stays off)\n'
    fi

    if [ -n "$FFMPEG_HINT$FPCALC_HINT" ]; then
        printf '\nInstall on this system:\n'
        [ -n "$FFMPEG_HINT" ] && printf '  %s\n' "$FFMPEG_HINT"
        [ -n "$FPCALC_HINT" ] && printf '  %s\n' "$FPCALC_HINT"
    fi
    return $missing
}

detect

case "${1:-check}" in
    check)
        printf 'External tools\n'
        report || true
        ;;
    install)
        if [ -z "$INSTALL_CMD" ]; then
            printf 'No package manager detected. Install manually:\n\n'
            printf '  %s\n  %s\n' "$FFMPEG_HINT" "$FPCALC_HINT"
            exit 1
        fi
        printf 'Running: %s\n\n' "$INSTALL_CMD"
        $INSTALL_CMD
        printf '\n'
        report || true
        ;;
    *)
        printf 'usage: %s [check|install]\n' "$0" >&2
        exit 2
        ;;
esac
