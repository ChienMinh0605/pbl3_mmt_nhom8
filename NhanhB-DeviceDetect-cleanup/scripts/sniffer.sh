#!/usr/bin/env bash
set -eo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
action="${1:-build}"
profile="${2:-activity}"

case "$profile" in
  activity) defaults='sdkconfig.defaults;sdkconfig.activity' ;;
  probe) defaults='sdkconfig.defaults' ;;
  probe-fixed) defaults='sdkconfig.defaults;sdkconfig.fixed' ;;
  *) echo 'Profile: activity, probe hoặc probe-fixed.' >&2; exit 2 ;;
esac

args=()
case "$action" in
  build|menuconfig) ;;
  flash)
    port="${3:-}"
    [[ -c "$port" && -r "$port" && -w "$port" ]] || {
      echo 'Cần chỉ định cổng USB–UART đã xác nhận và có quyền đọc/ghi.' >&2
      exit 2
    }
    if command -v fuser >/dev/null 2>&1 && fuser -s "$port"; then
      echo "Cổng $port đang được sử dụng. Ngắt kết nối sniffer và đóng serial monitor trước khi nạp." >&2
      exit 2
    fi
    args=(-p "$port" -b 460800)
    ;;
  *) echo 'Dùng: bash scripts/sniffer.sh {build|menuconfig|flash} {activity|probe|probe-fixed} [PORT]' >&2; exit 2 ;;
esac

if ! command -v idf.py >/dev/null 2>&1; then
  idf_export="${IDF_PATH:-$HOME/esp/esp-idf}/export.sh"
  [[ -f "$idf_export" ]] || { echo 'Cần ESP-IDF 5.5.4. Không tìm thấy export.sh.' >&2; exit 1; }
  source "$idf_export"
fi

cd "$ROOT/firmware/sniffer"
exec idf.py -B "build/$profile" -D IDF_TARGET=esp32c3 \
  -D "SDKCONFIG=sdkconfig.$profile.local" -D "SDKCONFIG_DEFAULTS=$defaults" "${args[@]}" "$action"
