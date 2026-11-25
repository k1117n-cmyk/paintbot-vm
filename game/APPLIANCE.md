# 段階8：対戦選択画面

Zero 2 Wの10インチモニターに対戦選択画面を表示し、操作者の開始操作を待つ。
自動起動設定の適用、OS再起動後の待機とSSH再接続、q終了後の再表示は確認済み。
ログ量制限・バックアップ/復元・性能測定の手順は [MAINTENANCE.md](MAINTENANCE.md) を参照。

## 手動で画面を開く

Zero 2 Wにつないだキーボードと10インチモニターのターミナルで実行する。

```sh
cd ~/paintbot-vm
game/build/paint-bots menu
```

登録されたボットが名前順に表示される。番号を2〜4個、希望するID順に空白で区切って入力する。
例えば `3 1` なら、一覧の3番がID 1、1番がID 2になる。
参加者を確認して `y` または `Y` を入力すると試合が始まる。それ以外は取り消す。

一覧は1ページ8件。`n` は次ページ、`p` は前ページ、`r` は再読込、`q` は終了。
番号は全ページの通し番号で、登録0〜1体でも画面を開いて待機できる。
登録名・ファイルの規則は [REGISTRATION.md](REGISTRATION.md) と同じ。
選択を取り消したりページを移動したりしても、試合は始まらない。

試合は既存の観戦画面で200ターン実行する。終了後の画面はEnterを押すまで残る。
Enterを押すと次の対戦を選べる。試合に失敗した場合も終了状態を表示して戻れる。
試合中のCtrl-Cは試合を中断し、Enterで選択へ戻る。選択中のCtrl-Cは画面を終了する。

## 自動起動の前に実機の構成を確認する

```sh
cd ~/paintbot-vm
python3 game/boot_info.py
```

これはOS・コンソール・gettyサービスなどの現在の情報を表示する読み取り専用の確認。
サービスの追加・有効化、ログイン設定・ユーザー権限の変更、再起動は行わない。
表示内容から10インチ側のコンソールとログイン構成を確認し、自動起動の設定を具体化する。
設定ファイルと反映・戻し方を用意して確認してから実機へ適用する。

## ローカル検証

ビルド後にプロジェクト直下で `python3 game/test_menu.py`、または `make -C game test-menu`。
疑似端末と実VMの2体戦を含むため、約40秒以上かかる。
既存回帰とビルドは並行させない。

自動起動と再起動確認は完了。ログ保存量制限、バックアップ・復元、性能測定は別途記録する。
これらが揃うまでは段階8全体を完了としない。

## 現行の自動起動設定と通常ログインへの復帰

設定は [systemd/paintbot-menu.service](systemd/paintbot-menu.service)、初回の適用と復元は
[manage_menu_service.py](manage_menu_service.py) を使う。実機はsystemd 257、tty1に専用メニューが稼働中。
ログ分離を適用した後に通常ログインへ戻す場合は、先にMAINTENANCE.mdのログ設定取り消しを行う。

- `pi` ユーザーで、プロジェクト直下から `paint-bots menu` を実行する。
- tty1の通常ログインを専用画面へ置き換える。現在のtty1ログインセッションは終了するため、
  手動メニューは先にqで終了し、適用・復元のコマンドはMacからSSHで実行する。
- SSHの設定・アカウント・ユーザー権限とベンダーgettyファイルは変更しない。
- 自動起動時はqで終了しても3秒後に画面を再表示する。試合は勝手に始めない。
  1分に10回の起動を超えると再試行を停止する。手動起動時のqは従来どおり終了する。
- 診断はサービスのjournal、画面と試合表示はtty1へ出す。ログ保存上限は後続の別作業。
- 元のgetty状態とサービス内容を `/var/lib/paintbot-menu/setup-*` に保存する。
  途中失敗時は元のgettyへ戻す。復元にも失敗した場合は `recovery-required` としてバックアップを残す。
- 既存サービスは上書きせず、対象のバイナリ・起動構成・サービス定義が確認済みの内容と
  異なる場合は停止する。管理者が後からサービス内容を変えた場合も、自動で削除して戻さない。

以下のcheck/installは初回導入前専用。現在は導入済みなので再実行しない。
初回導入時の、SSHから行う読み取り確認（設定変更なし）：

```sh
cd ~/paintbot-vm
python3 game/manage_menu_service.py check
```

適用前に `systemd-analyze verify` を実機で実行する。確認が通り、設定変更が承認された後に実行する：

```sh
sudo python3 game/manage_menu_service.py install
```

これは自動では再起動せず、その場でtty1を専用画面へ切り替え、次回起動時も有効にする。
`MENU_SETUP_EXIT=0` と `SETUP_BACKUP=`、`RESTORE_COMMAND=` を保存する。
通常のログイン画面へ戻す場合は、その出力にある実際のバックアップパスを指定する：

```text
sudo python3 game/manage_menu_service.py restore /var/lib/paintbot-menu/setup-実際の名前
```

復元は専用サービスを停止・無効化し、今回のファイルだけを削除して、gettyを有効化・起動する。
バックアップは残す。適用・復元ともSSH接続内で実行し、tty1からは実行しない。

準備のローカル検証は `make -C game test-menu-service`。一時ファイルと模擬サービス管理で
適用・復元・失敗時の回復を確認するもので、実systemdの検証や再起動確認の代用にはしない。

仕様の参照元（実機と同じ257系）：
[端末・実行ユーザー](https://www.freedesktop.org/software/systemd/man/257/systemd.exec.html)、
[サービスの再起動](https://www.freedesktop.org/software/systemd/man/257/systemd.service.html)、
[競合サービスの順序](https://www.freedesktop.org/software/systemd/man/257/systemd.unit.html)。
