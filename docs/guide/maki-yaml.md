# maki.yaml 設定ガイド

maki.yaml はmakiの動作を定義する設定ファイルです。GitHub Actions のワークフロー構文に準拠した構造を採用しています。

リポジトリ直下の `maki.yaml` は個人環境用の設定として扱います。共有用の雛形は `maki.example.yaml` に置き、必要に応じてコピーして使います。

```bash
cp maki.example.yaml maki.yaml
```

## 全体構造

```yaml
on:        # トリガー定義（いつ・何をきっかけに）
  schedule:
    interval: 300
  <watcher名>:
    schedule: "cron式"
    steps:
      - run: ...

jobs:      # ジョブ定義（何をやるか）
  <ジョブ名>:
    on: <トリガー名>
    steps:
      - run: ...
      - uses: ...
```

## on: ブロック（トリガー定義）

### schedule

メインループの実行間隔を秒で指定します。

```yaml
on:
  schedule:
    interval: 300  # 5分ごとにtick
```

### Watcher

外部の状態変化を検出するトリガーです。shellコマンドを実行し、stdoutに出力があればイベントを生成します。

```yaml
on:
  github-issues:
    schedule: "*/10 * * * *"    # cron式（省略時は毎tick実行）
    steps:
      - name: Check assigned issues
        run: gh search issues --assignee=@me --state=open --limit=5
        cwd: /home/miyagi        # 作業ディレクトリ（省略時はカレント）
```

- `schedule`: cron式で実行タイミングを制御。省略すると毎tickで実行される。タイムゾーンはシステムのローカル時刻に従う
  - 例: `"*/10 * * * *"` = 10分ごと、`"0 9,18 * * 1-5"` = 平日9時と18時
- `steps[].run`: 実行するshellコマンド
- `steps[].cwd`: コマンドの作業ディレクトリ
- `steps[].name`: ステップの名前（ログ表示用）
- 複数ステップの場合、前のステップのstdoutが環境変数 `$PREV` で次のステップに渡される
- 最後のステップのstdoutがイベントのデータになる

## jobs: ブロック（ジョブ定義）

### 基本構造

```yaml
jobs:
  ジョブ名:
    on: <トリガー名>    # どのイベントで起動するか
    steps:              # 実行するステップの列
      - name: ステップ名
        run: shellコマンド
```

### on: （トリガー指定）

ジョブがどのイベントで起動するかを指定します。

| 値 | 意味 |
|---|---|
| `manual` | `maki do` コマンドで手動実行 |
| `schedule` | スケジュールトリガー |
| `<watcher名>` | 指定したwatcherがイベントを検出したとき |

### steps: （ステップ定義）

ステップには `run:` と `uses:` の2種類があります。1つのステップにはどちらか一方のみを指定してください（両方を同時に指定することはできません）。

#### run: （shellコマンド実行）

`env:` はジョブ単位 (`jobs.<job>.env`) とステップ単位 (`jobs.<job>.steps[].env`) の両方で指定できます。トップレベルの workflow `env:` はまだサポートしておらず、設定読み込み時にエラーになります。

```yaml
jobs:
  summarize:
    on: manual
    env:
      REPO_ROOT: /home/miyagi/dev/project
      SHARED_MODE: job
    steps:
      - name: Summarize
        run: ./scripts/summarize "$PREV"
        env:
          SHARED_MODE: step
          STEP_RESULT: "${{ steps.fetch.outputs.result }}"
```

- 優先順位は `OSの環境変数 < job.env < step.env < maki実行時の環境変数`
- `env:` のキーは文字列のみ。値はスカラーを受け付け、実行時には文字列化される
- `env:` の文字列値では `${{ steps.<名前>.outputs.<キー> }}` と `$PREV` を使用できる
- `PREV`, `MAKI_INPUTS`, `MAKI_PREV`, `MAKI_OUTPUT` などの maki 実行時の予約環境変数はユーザー定義値で上書きされず、`maki/agent` などのアクション実行にも渡らない

```yaml
- name: Summarize
  run: maki agent --model haiku "要約してください。$PREV"
  cwd: /home/miyagi/dev/project   # 作業ディレクトリ（省略時はカレント）
```

- shellコマンドを実行し、stdoutがそのステップの `outputs.result` になる
- 前ステップの出力は `$PREV` 環境変数で参照可能
- `${{ }}` 式も使用可能（実行前に展開される）

#### uses: （組み込みアクション / ローカルアクション）

`uses:` にはビルトインの `maki/...` と、`./` または `../` で始まるローカルアクションを指定できます。

前のステップの出力をどう処理するかを指定します。

| アクション | 動作 | outputs |
|---|---|---|
| `maki/agent` | ai-cliでAIエージェントを実行する | `result`: Agent出力 / `status`: completed, confirm, error / `session_id`: Agent session ID |
| `maki/report` | 前ステップの出力をターミナルに表示 | `result`: 前ステップの出力そのまま |
| `maki/auto` | 前ステップの出力を記録して次へ | `result`: 前ステップの出力そのまま |
| `maki/confirm` | ブラウザ/CLIでユーザー確認を求める | `result`: accept時は元の出力、edit時はユーザー入力 / `choice`: accept, reject, edit / `edit_text`: editの場合のユーザー入力 / `original`: confirmに渡された元の出力 |

##### maki/agent のオプション

```yaml
- name: Draft reply
  uses: maki/agent
  with:
    model: sonnet       # 省略時: haiku
    cwd: /path/to/repo  # 省略時: .
    timeout: 180        # 省略時: 180
    session_id: "${{ steps.previous.outputs.session_id }}"
    prompt: "返信案を作ってください。$PREV"
```

- `prompt`: 必須。Agentに渡す指示
- `model`: 使用するモデル。省略時は `haiku`
- `cwd`: Agentの作業ディレクトリ。省略時は `.`
- `timeout`: Agent完了待ちの秒数。省略時は `180`
- `session_id`: 既存Agent sessionを再開する場合に指定。空文字は未指定として扱う
- `with:` の文字列では `${{ steps.<名前>.outputs.<キー> }}` と `$PREV` を参照できる

##### maki/confirm のオプション

```yaml
- uses: maki/confirm
  with:
    open_browser: true   # 確認画面をブラウザで自動で開く（デフォルト: false）
```

##### ローカルPythonアクション

v1 では `runs.using: python` のみサポートします。外部リポジトリ参照は未対応です。

```yaml
- name: Echo locally
  uses: ./examples/local-python-action/echo
  with:
    message: "Reply draft. $PREV"
    prefix: "[local] "
```

アクションディレクトリには `maki-action.yaml` または `action.yaml` を置きます。

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

- `with:` の値は実行前に `${{ }}` と `$PREV` が解決される
- `env:` も `run:` ステップと同じ優先順位で適用され、ローカルアクションのプロセス環境に渡される
- `inputs` の `default` と `required` を適用する
- アクションは現在のPythonインタプリタで `runs.main` を実行する
- 作業ディレクトリはアクションディレクトリになる
- 環境変数 `MAKI_INPUTS`, `MAKI_PREV`, `MAKI_OUTPUT` が渡される
- 出力は stdout ではなく `MAKI_OUTPUT` のJSONを読む
- JSON はトップレベルのオブジェクト、または `{ "outputs": { ... } }` のどちらでもよい
- 出力値はすべて文字列として `steps.<名前>.outputs.<キー>` で参照できる
- 実例は `examples/local-python-action/echo/` を参照

### if: （条件分岐）

`${{ }}` 式でステップの実行条件を指定できます。条件がfalseの場合、ステップはスキップされます。

```yaml
- name: on-accept
  if: "${{ steps.review.outputs.choice == 'accept' }}"
  run: echo "承認されました"
```

サポートする式:
- `${{ steps.<名前>.outputs.<キー> }}` — ステップの出力を参照
- `${{ steps.<名前>.outputs.<キー> == '値' }}` — 等価比較
- `${{ steps.<名前>.outputs.<キー> != '値' }}` — 不等比較

### ステップ間のデータ受け渡し

GitHub Actions と同様に、各ステップの出力は `steps.<名前>.outputs.<キー>` で後続のステップから参照できます。

#### run: ステップの outputs

| キー | 値 |
|---|---|
| `result` | stdoutの内容 |

#### maki/confirm の outputs

| キー | 値 |
|---|---|
| `result` | accept時は元の出力、edit時はユーザー入力、reject時は空文字 |
| `choice` | `accept`, `reject`, `edit` のいずれか |
| `edit_text` | editの場合のユーザー入力（それ以外は空文字） |
| `original` | confirmに渡された元の出力 |

#### maki/agent の outputs

| キー | 値 |
|---|---|
| `result` | Agentの出力 |
| `status` | `completed`, `confirm`, `error` のいずれか |
| `session_id` | Agent session ID。取得できない場合は空文字 |

#### 参照方法

2つの方法で参照できます:

1. **`${{ }}` 式**（run:やif:の中で使用）
   ```yaml
   run: echo "${{ steps.generate.outputs.result }}"
   if: "${{ steps.review.outputs.choice == 'accept' }}"
   ```

2. **環境変数**（shellコマンド内で使用）
   ```yaml
   run: echo "$STEPS_GENERATE_RESULT"
   # 形式: $STEPS_<ステップ名>_<キー> （全て大文字、ハイフンはアンダースコアに変換）
   ```

## CLIコマンド

```bash
maki run                    # メインループ起動
maki run --once             # 1 tick だけ実行して終了
maki do "<指示>"             # on: manual のジョブを実行（最初にマッチしたジョブ）
maki do "<指示>" --job <名前> # 特定のジョブを名前で直接指定して実行（on: の値に関係なく実行される）
maki agent --model <m> "prompt"  # AI agentを実行してstdoutに出力（ジョブのstepで使用）
maki status                 # 設定の確認
maki watch confirm --token <t>   # 別ターミナルでconfirm要求を監視・応答
```

### maki do のトリガーマッチング

- `maki do "<指示>"` — イベント名が `manual` となり、`on: manual` のジョブのうち最初にマッチしたものが実行される
- `maki do "<指示>" --job <名前>` — ジョブ名で直接マッチする。ジョブの `on:` の値に関係なく、指定した名前のジョブが実行される。同名のジョブが `on: manual` でなくても実行可能

## 完全な例

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
      - name: revise
        if: "${{ steps.review.outputs.choice == 'edit' }}"
        uses: maki/agent
        with:
          model: sonnet
          session_id: "${{ steps.generate.outputs.session_id }}"
          prompt: "フィードバック：${{ steps.review.outputs.edit_text }}"
```
