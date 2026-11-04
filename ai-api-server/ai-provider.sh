# 全 API インスタンス共通の AI プロバイダ選択。start-*.sh から読み込む。
# opencode の無料枠が回復するまで antigravity を使う。戻すときはここを opencode にして
# `pm2 restart aisync-api-erp aisync-api-dealer aisync-api-realestate aisync-api-koseki aisync-api-nenkin`。
export AISB_AI_PROVIDER="${AISB_AI_PROVIDER:-antigravity}"
