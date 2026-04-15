# セキュリティ運用手順

## API アクセストークン設定（Must）

本アプリのバックエンドは共有シークレット (`API_ACCESS_TOKEN`) による
簡易認証とIPベースのレートリミット（300req/h, 60req/min）を実装しています。

### 1. トークンを生成

```bash
openssl rand -hex 32
# 例: 3f2a91b7c4d8e6f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5
```

### 2. バックエンド（VPS: srv1334941.hstgr.cloud）に設定

`systemd` サービス経由で起動している場合:

```bash
sudo systemctl edit ai-creator.service
```

以下を追記:

```ini
[Service]
Environment="API_ACCESS_TOKEN=<生成したトークン>"
Environment="FRONTEND_ORIGINS=https://kodawarimax.github.io,http://localhost:5174"
```

再起動:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ai-creator.service
```

### 3. GitHub Actions にシークレット登録

1. https://github.com/kodawarimax/ai-creator/settings/secrets/actions
2. **New repository secret**
3. Name: `VITE_API_TOKEN` / Value: `<手順1と同じトークン>`

### 4. 再デプロイ

`main` にプッシュすればGitHub Actionsが新トークン埋め込みで再ビルド。

### 5. 検証

```bash
# トークンなしで 401 が返ることを確認
curl -i https://srv1334941.hstgr.cloud/api/templates
# → HTTP/1.1 401 Unauthorized

# トークンありで 200 が返ることを確認
curl -i -H "X-API-Token: <トークン>" https://srv1334941.hstgr.cloud/api/templates
# → HTTP/1.1 200 OK

# ヘルスチェック（認証不要）
curl https://srv1334941.hstgr.cloud/health
# → {"status":"healthy","version":"2.1.0","auth_enabled":true}
```

## トークンローテーション

1. 手順1 で新トークンを生成
2. GitHub Secrets を更新 → main へ空コミットで再ビルド
3. Actions 完了後にVPS の環境変数を更新 → `systemctl restart`
4. 順序を守れば停止時間ゼロ

## 注意事項

- `API_ACCESS_TOKEN` が未設定の場合、バックエンドは **開発モード**（認証なし）で起動
- この状態ではログに警告出力: `API_ACCESS_TOKEN is not set — /api endpoints are UNAUTHENTICATED`
- 本番では必ず設定すること
- レートリミットは memory:// (プロセス内) なので、複数 worker の場合は Redis 等への移行を検討

## 既知の制約

- フロントバンドルにトークンは含まれる（devtoolsで見える）
- → 完全な防御にはならないが、**IPレートリミットと合わせて自動スクリプトによる悪用は抑止**
- 本格運用では Supabase JWT 認証への移行を推奨（開発ロードマップ参照）
