# maki 概念設計

## 設計思想

makiはオーケストレーター（指揮者）である。自分では判断・作業をせず、「いつ・何を・誰にやらせるか」を制御する。設定ファイルはGitHub Actionsのワークフロー構文に準拠し、ジョブのstepからshellコマンドとしてAI agentを実行する。確認フローはstep outputsベースで実現し、session管理の複雑さを排除している。

## 登場する概念

```
maki
├── Core           … ループ制御とジョブstepの実行制御
├── Job            … GA風のstep列。run:(shell) と uses:(組み込みaction) で構成
├── Agent          … AI CLIでspawnされる作業者。stepのrun:からshellコマンドとして実行される
├── Context        … 状況・判断材料を保持する
│   ├── LoopContext     … ループ自体の状態（何tick目か、前回何をしたか等）
│   └── TaskContext     … 業務タスクごとの定義と実行時の文脈
├── Event          … 「何か起きた」を表す統一的なデータ
├── Watcher        … 何を監視するかの定義。shellコマンドで外部状態を確認しEventを生成
├── UserInput      … ユーザーとの対話窓口（問いかけ発信＋入力受理＋confirm応答）
├── Confirm        … step outputsベースの確認フロー。ブラウザUI / CLI / 通知で応答
└── Schedule       … いつ動くか（メインloop間隔 + watcherごとのcron式）
```

## 概念の関係

```
  ┌───────────┐   ┌───────────┐   ┌──────────┐
  │  Watcher  │   │ Schedule  │   │UserInput │
  │(shell実行) │   │(cron式)   │   │(対話窓口) │
  └─────┬─────┘   └─────┬─────┘   └────┬─────┘
        │               │              │
        └───────┐       │       ┌──────┘
                ▼       ▼       ▼
              ┌───────────────────┐
              │      Event        │
              └─────────┬─────────┘
                        │
                        ▼
                  ┌───────────┐       ┌─────────┐
                  │   Core    │◄─────▶│ Context │
                  │(orchestr.)│       └────┬────┘
                  └─────┬─────┘      ┌─────┴─────┐
                        │            ▼           ▼
                        │     LoopContext   TaskContext
                        │
                        ▼ Job steps を順に実行
              ┌─────────────────────┐
              │    run: (shell)     │──▶ Agent (AI CLI)
              │    uses: (action)   │──▶ maki/confirm, maki/report, maki/auto
              └─────────┬───────────┘
                        │
              step outputs (${{ }})
                        │
              ┌─────────┼──────────┐
              ▼         ▼          ▼
          outputs    if: 条件    $PREV
          .result    分岐       環境変数
          .choice
          .edit_text
```

## 各概念の責務

| 概念 | 責務 | 例 |
|------|------|----|
| **Core** | ループ制御とジョブstepの実行制御。Eventに応じてジョブを選択し、stepsを順に実行する。Core自身は判断・作業をしない | - |
| **Job** | GA風のstep列。`run:`（shell）と`uses:`（組み込みaction）で構成される。stepの出力は`${{ }}`式で後続stepから参照可能 | issue-summary, readme |
| **Agent** | AI CLIでspawnされる作業者。ジョブのstepから`maki agent`コマンドとして実行される | `maki agent --model haiku "要約して"` |
| **LoopContext** | ループの実行時状態を保持 | 「前回はSlack確認済み、Issue未確認」 |
| **Event** | Watcher・Schedule・UserInputの出力を統一的に表現するデータ。種別・発生元・内容を持つ | 「Slackメンション検出」「14:00の勤怠トリガー」「ユーザーが手動指示」 |
| **Watcher** | 何を監視するかの定義。shellコマンドで外部状態を確認し、変化があればEventを生成する | `gh search issues --assignee=@me` を実行 → 結果からEvent生成 |
| **UserInput** | ユーザーとの対話窓口。問いかけの発信、入力の受理、confirmの応答を担う | アイドル時の問いかけ / confirm応答（ブラウザUI / CLI） |
| **Confirm** | step outputsベースの確認フロー。ブラウザUI / CLI watchで応答。outputs: choice, edit_text, original | 「この内容で返信していい？ [accept/reject/edit]」 |
| **Schedule** | メインループの間隔 + watcherごとのcron式でタイミングを管理する | interval: 300 / `"*/10 * * * *"` |

## Agentの実行モデル

- Agentはジョブのstepからshellコマンドとしてspawnされる（`maki agent` or `ai-cli`）
- maki本体はAgentを直接管理せず、stepの`run:`でshellコマンドとして実行し、stdoutを受け取る
- 確認フローはAgentのsession管理ではなく、**step outputsベース**で実現する:
  - `run:` stepでAgentを実行 → stdoutが `outputs.result` になる
  - `uses: maki/confirm` stepで出力をユーザーに提示 → `outputs.choice` (accept/reject/edit) を返す
  - 後続stepで `if:` と `${{ steps.<name>.outputs.<key> }}` を使って分岐する
- この設計はGitHub Actions のワークフロー構文に準拠しており、session管理の複雑さを排除している

## Eventの役割

- **Watcher**、**Schedule**、**UserInput** の3つがEventの発生源となる
- Coreは発生源を問わず、統一的にEventを処理する
- これにより「外部変化の検出」「時間トリガー」「ユーザー指示」を同じフローで扱える

## Contextの役割

- **LoopContext** はCoreが毎tick更新する実行時状態。Watcherは前回の状態を見て差分だけ検出できる
- **TaskContext** は2つの側面を持つ:
  - **定義**: 設定ファイルからロードされる静的な情報（対象チャンネル、URL、使用Skill等）
  - **実行時**: タスク実行中に更新される動的な情報（最終確認時刻、処理済みID等）
- 「Slack監視」「Issue作業」「勤怠」それぞれに独立したTaskContextがある
- WatcherもAgentもContextを通じて「何を見るか」「何をするか」を知る

## 基本フロー

1. **Schedule** が「今動くべきか」を判定する（メインループのtick間隔 + watcherごとのcron式）
2. 時間が来たら **Watcher** がshellコマンドを実行し、変化があれば **Event** を生成
3. **Schedule** 自身も時間トリガーの **Event** を生成する（例: 勤怠時刻のcron式）
4. Eventが無ければ **Core** が **UserInput** を通じてユーザーに「何かやることある？」と問いかける
5. **Core** が Event を受け取り、対応するジョブの **steps** を順に実行する
6. 各stepの実行:
   - **`run:`**: shellコマンドを実行。stdoutが `outputs.result` になる。Agent実行もこの中で行う
   - **`uses:`**: 組み込みactionを実行。前stepの出力を受けて処理する
   - **`if:`**: `${{ }}` 式で条件評価し、falseならスキップ
7. `maki/confirm` stepに到達した場合:
   - ユーザーにブラウザUI / CLI / OS通知で確認要求を提示する
   - ユーザーが accept / reject / edit で応答する
   - 結果が `outputs.choice`, `outputs.edit_text` 等に格納される
   - 後続stepの `if:` で分岐処理を行う
8. **Context** を更新し、**Schedule** が次の起動時刻をセットしてスリープ
