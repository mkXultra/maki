# maki 実装ステータス

最終更新: 2026-04-13

## コア基盤

| 機能 | 状態 | 備考 |
|------|------|------|
| GA風YAML設定 (`on:` + `jobs:`) | done | `on:` のYAML boolean問題も対応済み |
| Watcher (shellコマンド + `$PREV`受け渡し) | done | 複数ステップ対応 |
| Watcher cron schedule | done | `croniter`使用。省略時は毎tick |
| Job steps (`run:` + `uses:`) | done | 排他（両方指定不可） |
| 組み込みaction (maki/confirm, maki/report, maki/auto) | done | `with:` オプション対応 |
| GA風step outputs (`${{ steps.<name>.outputs.<key> }}`) | done | 環境変数 `$STEPS_<NAME>_<KEY>` でも参照可 |
| if: 条件分岐 | done | `==`, `!=` 対応 |
| confirm ブラウザUI | done | `templates/dashboard.html` に分離済み |
| confirm CLI watch (`maki watch confirm`) | done | 別ターミナルから操作可能 |
| OS デスクトップ通知 | done | Linux (notify-send) / macOS (osascript) |
| HTTPサーバ (threading) | done | 127.0.0.1固定 + ランダムトークン |
| `maki agent` ヘルパー | done | ai-cli のラッパー |
| 設定バリデーション | done | trigger参照チェック、uses検証 |

## CLI コマンド

| コマンド | 状態 | 備考 |
|----------|------|------|
| `maki run` | done | メインループ常駐 |
| `maki run --once` | done | 1 tick実行 |
| `maki do "<指示>"` | done | on: manual のジョブ実行 |
| `maki do "<指示>" --job <名前>` | done | ジョブ名指定で直接実行 |
| `maki agent --model <m> "prompt"` | done | step内でのAI実行用 |
| `maki status` | done | 設定一覧表示 |
| `maki watch confirm --token <t>` | done | 別ターミナルからconfirm応答 |

## 要件カバレッジ

| ID | 要件 | 状態 | 備考 |
|----|------|------|------|
| F1 | 常駐監視 | done | `maki run` + Watcher + cron schedule |
| F2 | Slack監視・応答 | not started | Watcher基盤はあるが、具体的なSlack用job設定は未作成 |
| F3 | 実行前の確認 | done | maki/confirm + ブラウザUI + CLI watch |
| F4 | ループ制御 | done | schedule.interval + watcher cron |
| F5 | アイドル時の問いかけ | partial | ターミナル上のみ。ブラウザUIからの問いかけは未対応 |
| F6 | Issue取得・作業準備 | partial | github-issues watcherで取得は動作。作業準備ジョブは未整備 |
| F7 | Issue実装指示 | not started | ジョブ定義次第で可能だが未作成 |
| F8 | 勤怠自動入力 | not started | cronトリガー対応済み。具体的なジョブ未作成 |
| F9 | 手動タスク実行 | done | `maki do` |
| F10 | コンテキスト・スキル管理 | done | maki.yamlで設定管理 |
| F11 | 音声入力 | not started | Stretch目標 |

## ドキュメント

| ドキュメント | 状態 | 備考 |
|-------------|------|------|
| `docs/requirements.md` | done | 3モデルレビュー済み |
| `docs/conceptual-design.md` | done | v5、3モデルレビュー済み |
| `docs/basic-design.md` | done | プロトタイプ向け基本設計 |
| `docs/guide/maki-yaml.md` | done | 2モデル理解度検証済み（4ラウンド） |

## 次のステップ

- F2: Slack監視用のwatcher + jobを定義（agent-browser連携）
- F6-F7: Issue作業準備・実装ジョブの整備
- F8: 勤怠自動入力ジョブの作成
- F5: ブラウザUIからのアイドル問いかけ対応
- `maki run` の常駐テスト（実運用）
