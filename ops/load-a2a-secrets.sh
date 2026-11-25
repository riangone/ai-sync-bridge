# source 用。ops/secrets/a2a.env があれば環境変数として読み込む(無ければ A2A キーは未設定のまま=無効)。
_aisb_a2a_env="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/secrets/a2a.env"
if [ -f "$_aisb_a2a_env" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$_aisb_a2a_env"
  set +a
fi
unset _aisb_a2a_env
