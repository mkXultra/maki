# maki

日常の定型業務を自動監視・実行する軽量パッシブAI。

## 概要

**maki** はバックグラウンドで常駐し、Slack・GitHub・勤怠システムなどを定期監視して、必要なときにAIエージェントを起動し作業を代行します。実行前にユーザーへ確認を取り、承認・却下・修正を受け付けながら安全に自動化を進めます。

## コンセプト

maki は**オーケストレーター（指揮者）**です。自分では判断・作業をせず、AI CLI（Claude, Codex等）のエージェントをspawnして「いつ・何を・誰にやらせるか」を制御します。

```
Watcher（監視）─→ Event ─→ Core（制御）─→ Agent（AI CLI）─→ 結果
                                               ↓
                                      確認要求 → ユーザー → accept / reject / edit
```

| 概念 | 役割 |
|------|------|
| **Core** | メインループ制御。唯一のAgentのspawn主体 |
| **Watcher** | Slack・GitHub等を定期監視してEventを生成 |
| **Schedule** | 時刻・間隔指定でEventを生成（例: 勤怠時刻） |
| **Agent** | AI CLIで起動される作業者。session IDで中断・再開が可能 |
| **UserInput** | 確認要求のバイパス（accept / reject / edit）とアイドル時の問いかけ |

## インストール

```bash
uv tool install .
```

## 設定

`maki.yaml`（カレントディレクトリ）または `~/.config/maki/config.yaml` に記述します。

このリポジトリでは `maki.yaml` は個人環境用としてGit管理から外しています。まずサンプルをコピーして、`cwd` などのパスを自分の環境に合わせます。

```bash
cp maki.example.yaml maki.yaml
```

```yaml
on:
  schedule:
    interval: 300  # tick間隔（秒）

  github-issues:           # Watcherの定義
    steps:
      - name: Check assigned issues
        run: gh search issues --assignee=@me --state=open --limit=5
        cwd: /home/yourname

jobs:
  issue-summary:
    on: github-issues      # どのWatcherのEventで起動するか
    env:
      REPO_ROOT: /home/yourname/project
      SHARED_MODE: job
    steps:
      - name: Summarize
        uses: maki/agent
        env:
          SHARED_MODE: step
          SUMMARY_SOURCE: "$PREV"
        with:
          model: haiku
          cwd: /home/yourname
          prompt: "以下のIssue一覧を要約してください。$PREV"
      - uses: maki/report  # 結果を表示

  kintai:
    on: manual             # 手動実行のみ
    steps:
      - name: Clock in/out
        uses: maki/agent
        with:
          model: sonnet
          prompt: "勤怠システムに出退勤を入力する"
      - uses: maki/confirm # 実行前にユーザー確認を取る
```

`env:` はジョブ単位 (`jobs.<job>.env`) とステップ単位 (`jobs.<job>.steps[].env`) で指定できます。値は文字列・数値・真偽値・null を受け付け、実行時には文字列として渡されます。トップレベルの workflow `env:` はまだ未対応で、設定読み込み時にエラーになります。

優先順位は `OSの環境変数 < job.env < step.env < maki実行時の予約環境変数` です。たとえば `PREV` やローカルPythonアクション向けの `MAKI_INPUTS`, `MAKI_PREV`, `MAKI_OUTPUT` はユーザー定義の `env:` では上書きできず、`maki/agent` にも渡りません。`env:` の文字列値では `${{ steps... }}` と `$PREV` も実行前に解決されます。

### ビルトインアクション

ステップの `uses:` に指定できるビルトインアクションは以下の通りです。

| アクション | 説明 |
|-----------|------|
| `maki/agent` | ai-cliでAIエージェントを実行し、結果とsession IDをoutputsに格納する |
| `maki/confirm` | 前のステップの出力をユーザーに提示し、accept / reject / edit を待つ |
| `maki/report` | 前のステップの出力を表示して終了 |
| `maki/auto` | ユーザー確認なしで自動続行 |

`maki/agent` は `with.prompt` を必須とし、`model` / `cwd` / `timeout` / `session_id` を指定できます。出力は `result`, `status`, `session_id` です。後続stepでは `steps.<name>.outputs.session_id` を渡して同じAgent sessionを再開できます。

```yaml
- name: Draft
  uses: maki/agent
  with:
    model: sonnet
    prompt: "返信案を作ってください。$PREV"

- name: Revise
  uses: maki/agent
  with:
    model: sonnet
    session_id: "${{ steps.Draft.outputs.session_id }}"
    prompt: "修正してください: ${{ steps.review.outputs.edit_text }}"
```

### ローカルPythonアクション

`uses:` にはビルトインの `maki/...` に加えて、`./` または `../` で始まるローカルアクションも指定できます。v1 では `runs.using: python` のみ対応します。

```yaml
- name: Echo locally
  uses: ./examples/local-python-action/echo
  with:
    message: "Reply draft. $PREV"
    prefix: "[local] "
```

アクションディレクトリには `maki-action.yaml` または `action.yaml` を置きます。例は `examples/local-python-action/echo/` にあります。

```yaml
name: echo
description: Example local Python action
inputs:
  message:
    required: true
  prefix:
    default: ""
runs:
  using: python
  main: action.py
```

実行時は現在のPythonインタプリタで `runs.main` を起動し、以下を環境変数で渡します。

- `MAKI_INPUTS`: `${{ }}` と `$PREV` を解決済みの入力JSON
- `MAKI_PREV`: 前ステップの `outputs.result`
- `MAKI_OUTPUT`: アクションがJSONを書き込む出力ファイルパス
- ジョブ/ステップの `env:` も同時に渡されるが、上記の `MAKI_*` 予約変数が優先される

出力は stdout ではなく `MAKI_OUTPUT` のJSONから読み取ります。トップレベルのオブジェクト、または `{ "outputs": { ... } }` のどちらでも構いません。すべて文字列として後続stepへ渡されます。

## 使い方

```bash
# メインループを起動（常駐監視）
maki run

# 1 tick だけ実行して終了
maki run --once

# 任意タスクを手動で指示
maki do "PRのレビューをして"

# 現在のループ状態を表示
maki status

# AIエージェントをその場で実行（ジョブステップからも使用）
maki agent --model haiku "Issueを要約してください"
maki agent --model sonnet --cwd /path/to/project "コードをレビューして"
```

## 確認（Confirm）インターフェース

ジョブに `uses: maki/confirm` が含まれる場合、Agentの出力をユーザーが確認してから続行します。

確認には2つの方法があります。

### 1. Webダッシュボード（推奨）

`maki run` または `maki do` 起動時に表示されるURLをブラウザで開きます。

```
Dashboard: http://127.0.0.1:7831/?token=xxxx
```

画面上で **Accept / Reject / Edit** を選択できます。

### 2. CLIで確認

別ターミナルで以下を実行します。

```bash
maki watch confirm --token <上記URLのtoken値>
```

プロンプトで `[a]ccept / [r]eject / [e]dit` を選択します。

## 実行フロー

1. **Schedule** が起動タイミングを判定
2. **Core** が **Watcher** の定義に従い監視ステップを実行 → **Event** を生成
3. Eventが無ければ **UserInput** でユーザーに「何かやることある？」と問いかけ
4. **Core** が Event にマップされた **Job** のステップを順に実行
5. `maki/confirm` ステップで Agentの結果をユーザーに提示:
   - **accept**: 前stepの結果を承認して後続stepへ渡す
   - **reject**: 空の結果を返し、後続stepで分岐できる
   - **edit**: フィードバックを `edit_text` として返し、必要なら `maki/agent` に `session_id` と一緒に渡して再開する
6. **Context** を更新し、**Schedule** が次の起動時刻をセットしてスリープ

## モジュール構成

```
src/maki/
├── __init__.py    # CLI エントリポイント（click）
├── core.py        # メインループ
├── agent.py       # Agent spawn / session管理
├── watcher.py     # Watcher定義の読み込みとEvent生成
├── event.py       # Event データ構造
├── user_input.py  # ユーザー対話（問いかけ・確認バイパス）
├── context.py     # LoopContext / TaskContext
├── config.py      # 設定ファイル読み込み
├── confirm.py     # 確認要求の状態管理
└── web.py         # 確認用Webダッシュボード（ポート7831）
```

## 要件・設計

詳細は `docs/` ディレクトリを参照してください。

- [要件定義](docs/requirements.md)
- [概念設計](docs/conceptual-design.md)
- [基本設計](docs/basic-design.md)
