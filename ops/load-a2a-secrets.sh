# source 用。ops/secrets/a2a.env から「引数で指定したキーだけ」を環境変数として読み込む。
#   例: source ../ops/load-a2a-secrets.sh AISB_A2A_ERP_PEER_KEY AISB_A2A_CRM_PEER_KEY
# 最小権限: 各プロセスは自分の送信キーと受信検証用キーだけを持つ(他システムの管理キーは渡さない)。
# 引数なしは何も読み込まない。ファイルが無ければ未設定のまま(=その A2A 経路は無効)。
_aisb_a2a_env="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/secrets/a2a.env"
if [ -f "$_aisb_a2a_env" ] && [ "$#" -gt 0 ]; then
  for _aisb_k in "$@"; do
    _aisb_line="$(grep -m1 "^${_aisb_k}=" "$_aisb_a2a_env" || true)"
    if [ -n "$_aisb_line" ]; then
      export "${_aisb_k}=${_aisb_line#*=}"
    fi
  done
fi
unset _aisb_a2a_env _aisb_k _aisb_line
