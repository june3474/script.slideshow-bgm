#!/usr/bin/env bash
# Collect copy/paste-friendly diagnostics for Slideshow-BGM bug reports.
# Usage: ./collect-bug-report.sh [KODI_DATA_DIRECTORY]

set -u
set -o pipefail

ADDON_ID="script.slideshow-bgm"
MAX_LOG_LINES=200

usage() {
    cat <<'EOF'
Usage: collect-bug-report.sh [KODI_DATA_DIRECTORY]

Without an argument, the script searches the standard Kodi locations on
Linux and macOS. Pass Kodi's data directory for a portable or custom install.
EOF
}

first_existing_directory() {
    local candidate
    for candidate in "$@"; do
        if [ -n "$candidate" ] && [ -d "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

first_existing_file() {
    local candidate
    for candidate in "$@"; do
        if [ -n "$candidate" ] && [ -f "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

xml_setting() {
    local file=$1
    local setting_id=$2
    local line

    [ -f "$file" ] || return 1
    line=$(grep -E -m 1 \
        "<setting[[:space:]][^>]*id=['\"]${setting_id}['\"]" \
        "$file" 2>/dev/null) || return 1

    printf '%s\n' "$line" | sed -n \
        -e 's/.*<setting[^>]*>\([^<]*\)<\/setting>.*/\1/p' \
        -e 's/.*[[:space:]]value="\([^"]*\)".*/\1/p' \
        | head -n 1
}

xml_attribute() {
    local file=$1
    local attribute=$2

    [ -f "$file" ] || return 1
    awk '
        /<addon[[:space:]]/ { found = 1 }
        found { print }
        found && />/ { exit }
    ' "$file" | tr '\n' ' ' | sed -n \
        "s/.*[[:space:]]${attribute}=\"\([^\"]*\)\".*/\1/p" \
        | head -n 1
}

xml_element() {
    local file=$1
    local element=$2

    [ -f "$file" ] || return 1
    sed -n "s:.*<${element}>\([^<]*\)</${element}>.*:\1:p" "$file" | head -n 1
}

detect_platform() {
    local kernel
    local version
    local architecture

    kernel=$(uname -s 2>/dev/null || printf 'Unknown')
    architecture=$(uname -m 2>/dev/null || printf 'Unknown')
    if [ "$kernel" = "Darwin" ]; then
        version=$(sw_vers -productVersion 2>/dev/null || printf 'Unknown')
        printf 'macOS %s (%s)\n' "$version" "$architecture"
        return
    fi

    version=""
    if [ -r /etc/os-release ]; then
        version=$(sed -n 's/^PRETTY_NAME=//p' /etc/os-release | head -n 1)
        version=${version#\"}
        version=${version%\"}
        version=${version#\'}
        version=${version%\'}
    fi
    [ -n "$version" ] || version="$kernel"
    printf '%s; kernel %s (%s)\n' \
        "$version" "$(uname -r 2>/dev/null || printf 'Unknown')" "$architecture"
}

detect_kodi_version() {
    local log_file=$1
    local line

    [ -f "$log_file" ] || return 1
    line=$(grep -m 1 'Starting Kodi' "$log_file" 2>/dev/null) || return 1
    printf '%s\n' "$line" | sed 's/.*Starting Kodi[[:space:]]*//'
}

redact_log() {
    awk -v home="${HOME:-}" -v source="${source_path:-}" '
        function replace_literal(text, needle, replacement, position) {
            if (needle == "") {
                return text
            }
            while ((position = index(text, needle)) != 0) {
                text = substr(text, 1, position - 1) replacement \
                    substr(text, position + length(needle))
            }
            return text
        }
        {
            line = replace_literal($0, source, "<redacted>")
            line = replace_literal(line, home, "~")
            print line
        }
    ' | sed \
        -e 's/\(source=\(PLAYLIST\|DIRECTORY\):\).*\([[:space:]]shuffle=\)/\1<redacted>\3/' \
        -e 's|\([[:alpha:]][[:alnum:]+.-]*://\)[^/@[:space:]]*@|\1<credentials>@|g'
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    usage
    exit 0
fi
if [ "$#" -gt 1 ]; then
    usage >&2
    exit 2
fi

custom_data_dir=${1:-}
kernel=$(uname -s 2>/dev/null || printf 'Unknown')

if [ -n "$custom_data_dir" ]; then
    kodi_data_dir=$custom_data_dir
elif [ "$kernel" = "Darwin" ]; then
    kodi_data_dir=$(first_existing_directory \
        "$HOME/Library/Application Support/Kodi" 2>/dev/null || true)
else
    kodi_data_dir=$(first_existing_directory \
        "$HOME/.kodi" \
        "$HOME/.var/app/tv.kodi.Kodi/data" \
        "$HOME/.var/app/tv.kodi.Kodi" \
        "$HOME/snap/kodi/current/.kodi" \
        "/storage/.kodi" 2>/dev/null || true)
fi

if [ -z "${kodi_data_dir:-}" ] || [ ! -d "$kodi_data_dir" ]; then
    printf 'Kodi data directory was not found.\n' >&2
    printf 'Pass it explicitly: %s /path/to/kodi-data\n' "$0" >&2
    exit 1
fi

userdata_dir="$kodi_data_dir/userdata"
gui_settings="$userdata_dir/guisettings.xml"
advanced_settings="$userdata_dir/advancedsettings.xml"
addon_settings="$userdata_dir/addon_data/$ADDON_ID/settings.xml"
addon_manifest="$kodi_data_dir/addons/$ADDON_ID/addon.xml"

if [ "$kernel" = "Darwin" ]; then
    log_file=$(first_existing_file \
        "$HOME/Library/Logs/kodi.log" \
        "$kodi_data_dir/temp/kodi.log" \
        "$kodi_data_dir/kodi.log" 2>/dev/null || true)
    old_log_file=$(first_existing_file \
        "$HOME/Library/Logs/kodi.old.log" \
        "$kodi_data_dir/temp/kodi.old.log" \
        "$kodi_data_dir/kodi.old.log" 2>/dev/null || true)
else
    log_file=$(first_existing_file \
        "$kodi_data_dir/temp/kodi.log" \
        "$kodi_data_dir/kodi.log" 2>/dev/null || true)
    old_log_file=$(first_existing_file \
        "$kodi_data_dir/temp/kodi.old.log" \
        "$kodi_data_dir/kodi.old.log" 2>/dev/null || true)
fi

kodi_version=$(detect_kodi_version "${log_file:-}" 2>/dev/null || true)
[ -n "$kodi_version" ] || \
    kodi_version=$(detect_kodi_version "${old_log_file:-}" 2>/dev/null || true)
[ -n "$kodi_version" ] || kodi_version="Not detected"

skin_id=$(xml_setting "$gui_settings" "lookandfeel.skin" 2>/dev/null || true)
[ -n "$skin_id" ] || skin_id="Not detected"

addon_version=$(xml_attribute "$addon_manifest" "version" 2>/dev/null || true)
if [ -z "$addon_version" ] && [ -n "${log_file:-}" ]; then
    addon_version=$(grep -F '[slideshow-BGM] session start: version=' "$log_file" \
        2>/dev/null | tail -n 1 \
        | sed -n 's/.*session start: version=\([^[:space:]]*\).*/\1/p')
fi
[ -n "$addon_version" ] || addon_version="Not detected"

source_kind=$(xml_setting "$addon_settings" "type" 2>/dev/null || true)
[ -n "$source_kind" ] || source_kind="Not detected"

source_path=""
playlist_format="Not applicable"
if [ "$source_kind" = "Playlist" ]; then
    source_path=$(xml_setting "$addon_settings" "playlist" 2>/dev/null || true)
    case $(printf '%s' "$source_path" | tr '[:upper:]' '[:lower:]') in
        *.m3u) playlist_format=".m3u" ;;
        *.pls) playlist_format=".pls" ;;
        *.xsp) playlist_format=".xsp" ;;
        *) playlist_format="Not detected" ;;
    esac
elif [ "$source_kind" = "Directory" ]; then
    source_path=$(xml_setting "$addon_settings" "directory" 2>/dev/null || true)
fi

debug_logging_gui=$(xml_setting "$gui_settings" "debug.showloginfo" 2>/dev/null || true)
case $(printf '%s' "$debug_logging_gui" | tr '[:upper:]' '[:lower:]') in
    true|1) debug_logging_gui=enabled ;;
    false|0) debug_logging_gui=disabled ;;
    *) debug_logging_gui="" ;;
esac

loglevel=$(xml_element "$advanced_settings" "loglevel" 2>/dev/null || true)
case "$loglevel" in
    -1|0) loglevel_enabled=disabled ;;
    1|2) loglevel_enabled=enabled ;;
    *) loglevel_enabled="" ;;
esac

if [ "$debug_logging_gui" = enabled ] || [ "$loglevel_enabled" = enabled ]; then
    debug_logging="Enabled"
elif [ "$debug_logging_gui" = disabled ] || [ -n "$loglevel_enabled" ]; then
    debug_logging="Disabled"
else
    debug_logging="Not detected"
fi

diagnostic_log=""
diagnostic_log_name=""
if [ -n "${log_file:-}" ]; then
    diagnostic_log=$(grep -F '[slideshow-BGM]' "$log_file" 2>/dev/null \
        | tail -n "$MAX_LOG_LINES" | redact_log || true)
    [ -z "$diagnostic_log" ] || diagnostic_log_name="kodi.log"
fi
if [ -z "$diagnostic_log" ] && [ -n "${old_log_file:-}" ]; then
    diagnostic_log=$(grep -F '[slideshow-BGM]' "$old_log_file" 2>/dev/null \
        | tail -n "$MAX_LOG_LINES" | redact_log || true)
    [ -z "$diagnostic_log" ] || diagnostic_log_name="kodi.old.log"
fi

cat <<EOF
<!-- Copy the report below into the GitHub bug report. -->

## Automatically collected environment

- Kodi version: $kodi_version
- Platform: $(detect_platform)
- Skin: $skin_id
- Slideshow-BGM version: $addon_version
- Music source kind: $source_kind
- Playlist format: $playlist_format
- Kodi debug logging: $debug_logging

## Slideshow-BGM log

Source: ${diagnostic_log_name:-No matching log found}

\`\`\`text
${diagnostic_log:-No [slideshow-BGM] lines were found. Reproduce the problem, then run this script again.}
\`\`\`

**Review the output for personal information before posting it publicly.**
EOF
