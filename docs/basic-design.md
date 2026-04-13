# maki 基本設計

## 概要

概念設計に基づき、実装に必要な設計を定義する。

## 設計方針

- 設定ファイルは **GitHub Actions のワークフロー構文に準拠** した構造を採用する（学習コストの低減）
- `on:` でトリガー（いつ・何をきっかけに）、`jobs:` でジョブ（何をやるか）を定義する
- ジョブのstepは `run:`（shellコマンド）と `uses:`（組み込みaction）の2種類
- ステップ間のデータ受け渡しは `${{ steps.<name>.outputs.<key> }}` 構文（GA準拠）
- AI agentの実行は `uses: maki/agent` を標準とする。shellコマンド（`maki agent` or `ai-cli`）も `run:` から利用できる
- confirm UIはlocalhostのHTTPサーバ（threading）で提供。ブラウザ/CLI両対応

## 設定ファイル

`~/.config/maki/config.yaml` もしくはプロジェクトルートの `maki.yaml`

詳細は `docs/guide/maki-yaml.md` を参照。

```yaml
on:
  schedule:
    interval: 300

  github-issues:
    schedule: "*/10 * * * *"
    steps:
      - name: Check assigned issues
        run: gh search issues --assignee=@me --state=open --limit=5
        cwd: /home/miyagi

jobs:
  issue-summary:
    on: github-issues
    steps:
      - name: Summarize
        uses: maki/agent
        with:
          model: haiku
          prompt: "Issue一覧を要約してください。$PREV"
      - uses: maki/report

  readme:
    on: manual
    steps:
      - name: generate
        uses: maki/agent
        with:
          model: sonnet
          prompt: "READMEを作成してください"
      - name: review
        uses: maki/confirm
        with:
          open_browser: true
      - name: apply
        if: "${{ steps.review.outputs.choice == 'accept' }}"
        run: echo "${{ steps.generate.outputs.result }}" > README.md
```

## CLIコマンド

```bash
maki run                          # メインループ起動
maki run --once                   # 1 tick だけ実行して終了
maki do "<指示>"                   # on: manual のジョブを実行
maki do "<指示>" --job <名前>      # 特定のジョブを名前指定で実行
maki agent --model <m> "prompt"   # AI agentを実行（ジョブのstepで使用）
maki status                       # 設定の確認
maki watch confirm --token <t>    # 別ターミナルでconfirm応答
```

## モジュール構成

```
src/maki/
├── __init__.py       # CLI エントリポイント（click）
├── core.py           # メインループ + step実行 + ${{}} 式評価
├── agent.py          # ai-cli spawn / wait / result ラッパー
├── watcher.py        # Watcher shellコマンド実行 + cron判定
├── event.py          # Event データ構造
├── config.py         # GA風YAML設定読み込み + バリデーション
├── confirm.py        # ConfirmStore（thread-safe共有キュー）
├── context.py        # LoopContext / TaskContext
├── user_input.py     # ターミナル用 idle prompt
├── web.py            # HTTPサーバ（confirm UI + API）
└── templates/
    └── dashboard.html  # confirm ダッシュボードHTML
```

## 組み込みaction

| action | 動作 | outputs |
|--------|------|---------|
| `maki/agent` | ai-cliでAgentを実行 | `result`, `status`, `session_id` |
| `maki/report` | 前stepの出力をターミナルに表示 | `result` |
| `maki/auto` | 前stepの出力を記録して次へ | `result` |
| `maki/confirm` | ブラウザ/CLIでユーザー確認を求める | `result`, `choice`, `edit_text`, `original` |

## confirm UI

- HTTPサーバは `maki run` 起動時にdaemonスレッドで立ち上げる（127.0.0.1固定 + ランダムトークン）
- confirm要求が来るとOS通知でURLを知らせる（自動でブラウザは開かない。`open_browser: true` 指定時のみ自動で開く）
- 応答手段は3つ: ブラウザUI / `maki watch confirm` / ターミナル直接入力
- ConfirmStoreで待機中のconfirmをthread-safeに管理し、応答があるまでCoreはブロックする
