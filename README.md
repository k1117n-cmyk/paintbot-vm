# paintbot-vm

![Language: C](https://img.shields.io/badge/Language-C-00599C)
![Tools: Python 3](https://img.shields.io/badge/Tools-Python%203-3776AB)
![Tested on: Raspberry Pi Zero 2 W](https://img.shields.io/badge/Tested%20on-Raspberry%20Pi%20Zero%202%20W-A22846)
![Tested on: macOS](https://img.shields.io/badge/Tested%20on-macOS-555555)
[![License: MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)

自作VM上のボットが戦う「ペイント合戦」「宝取り競争」と、人がキーで遊ぶ「迷路」「Dot Chase」を、共通メニューから選べるゲーム機です。
C言語で実装したVM・アセンブラ・ゲームホストと、アセンブリで書いたボットを収録しています。
Raspberry Pi Zero 2 W（Raspberry Pi OS Lite 32-bit）で動作を確認しています。
macOSでもビルドして対戦を試せます。

ボット対戦ではプログラムを作り、2〜4体を選んで対戦を観戦します。
迷路ではW/A/S/Dでプレイヤーを直接動かします。迷路の入力・描画・ゲーム処理はC側で行います。
Dot ChaseはVM上で動くパックマン風ゲームです。移動・餌・敵の追跡・勝敗をVMバイトコード内で処理します。

## 4本のゲームをメニューから選ぶ

以下は取得したリポジトリの最上位フォルダーで実行します。

```sh
git clone https://github.com/k1117n-cmyk/paintbot-vm.git
cd paintbot-vm
make run
```

VM・4本のゲーム・共通メニューをビルドし、VMセルフテストとペイント合戦の付属4体の初期登録を行ってからメニューを開きます。同名の登録済みボットは上書きしません。準備だけなら `make setup`、登録を行わずビルドだけなら `make` です。

- `1: Paintbot`：登録済みのペイント合戦ボットから2〜4体を選択します。同じ登録名の重複参加はできません。
- `2: Treasure`：宝取り競争の付属ボットから2〜4体を選択します。`1: seeker-h`、`2: seeker-v`、`3: right`、`4: wait`。同じ種類を複数選べます。2体戦は `1 2`、4体戦は `1 2 1 2` が例です。
- `3: Maze`：W/A/S/Dで移動、Rで最初から、Qでゲーム選択へ戻ります。端末ではEnter不要です。ゴールでクリアし、EnterまたはQで戻ります。[迷路の遊び方](maze/README.md)も参照してください。
- `4: Dot Chase`：W/A/S/Dで移動、入力がなければ停止、Rで最初から、Qでゲーム選択へ戻ります。全89個の餌を集めるとクリア、敵と重なるとゲームオーバーです。結果画面ではEnterでも戻れます。[遊び方とVM入出力仕様](dotchase/README.md)を参照してください。

ボット対戦では参加者を確認して `y` とEnterで開始します。試合後はEnterでボット選択へ、そこで `q` とEnterでゲーム選択へ戻ります。ゲーム選択での `q` はプログラム終了で、OSのシャットダウンは行いません。

両ボット対戦ゲームとも16×16マス、2〜4体、200ターンです。宝取り競争では固定配置36個・合計52点の宝を集めます。移動後にそのマスに1体だけいれば宝を取得でき、重なっている間は取得を保留します。迷路は17×9マスの固定盤面です。詳細は [宝取り競争の仕様](treasure/README.md) と [メニュー操作](console/README.md) を参照してください。

両ボット対戦ゲームのルールと表示はCのゲームホスト、ボットの判断はVMが担当します。VM起動・100ms期限・出力検証は `game/bot_runner.c`・`.h` を共用します。Dot Chaseには、`--game` 専用の描画・非ブロッキング入力・待機サービス（SYSCALL 4〜6）を追加しています。既存のVM命令形式とSYSCALL 0〜3は維持しています。

開発者のZero 2 WではDot Chaseの実機反映・自動検証、10インチ画面での操作、段階7反映後のOS再起動とメニュー自動表示を確認済みです。公開用のpi設定での実機適用は未実施です。

## 解説記事

[自作VMで動くペイント合戦ボットの仕組み―命令の実行から移動先の判断まで（UNIX Cafe）](https://pc-fan.net/handmade-vm-paint-battle-bots/)

3行のボットから始めて、VMの命令実行、盤面データの受け渡し、explorer・raiderが移動先を選ぶ仕組みを解説しています。
コードを読みながら仕組みを追いたい方はこちらを参照してください。

## 必要なもの

- Cコンパイラ（`cc`）と `make`
- Python 3（テスト、ボットのソース生成、実機管理ツール用）
- 観戦表示にはANSIカラー対応の端末（64桁×24行以上）

通常の対戦には外部の描画ライブラリやPythonパッケージは必要ありません。
自動起動やログ管理には、別途systemdを使います。

## ペイント合戦を単独でビルドして対戦する

```sh
git clone https://github.com/k1117n-cmyk/paintbot-vm.git
cd paintbot-vm
make -C vm
make -C game
game/build/paint-host --watch vm/build/handmade-vm game/build/explorer-h.bin game/build/raider-v.bin
```

観戦は1ターン約200ms、200ターンで約40秒かかります。
最終結果だけを見る場合は `--watch` を `--no-watch` に変更します。
指定するボットの順番がIDと開始位置を決めます。

## ルールと処理の流れ

- 16×16マス、2〜4体、200ターン。開始マスは各ボットの色です。
- 各ボットは上下左右への移動か待機を選び、移動先を自分の色に塗ります。
- 全員がターン開始時の同じ盤面を参照し、全員の行動がそろってから移動を判定します。
- 同じマスに複数のボットが到着したときは、そのマスの色を維持します。
- 待機や盤面外への移動でその場に留まった場合は塗りません。
- 200ターン後に最も多くのマスを塗ったボットが勝ち、同点なら引き分けです。

ゲームホストが盤面・得点・衝突を管理し、各ボットの判断をVMで実行します。
ボットごとに毎ターン新しいVMプロセスを起動するため、今回のボットはターン間の記憶を使いません。
1応答の期限は100msです。タイムアウト・不正出力・VMエラーはそのターンの待機として扱います。
ホスト自身のプロセス生成やVM起動の失敗は試合を中断します。

## 付属のボット

| ボット | 判断の方針 |
| --- | --- |
| `explorer-h` / `explorer-v` | 未塗装の隣接マスを優先 |
| `raider-h` / `raider-v` | 相手の色の隣接マスを優先 |
| `right` / `left` / `wait` | 右移動・左移動・待機の動作確認用 |
| `left15` | 最初の15ターンだけ左に移動 |
| `loop` / `invalid` | タイムアウト・不正出力の確認用 |

`h` と `v` は同じ優先度の候補を選ぶ際の巡回経路の違いです。
判断の説明と4体の登録手順は [game/PLAYING.md](game/PLAYING.md) を参照してください。

## 小さなボットを変更する

`game/bots/right.asm` は次の3行です。

```asm
MOVI R0, 68
SYSCALL 0
HALT
```

ASCIIコード68（`D`）を出力して右への移動を指示します。
行動は `W`（上）、`A`（左）、`S`（下）、`D`（右）、`X`（待機）です。
ファイルをコピーして数値を変更し、アセンブラでバイトコードへ変換できます。

```sh
cp game/bots/right.asm game/bots/my-bot.asm
# my-bot.asmを編集してから実行
vm/build/small-asm game/bots/my-bot.asm game/build/my-bot.bin
game/build/paint-host --watch vm/build/handmade-vm game/build/my-bot.bin game/build/explorer-h.bin
```

盤面を読んで判断する実装は `game/bots/explorer-h.asm` などを参照してください。
対戦用4体の共通の生成元は `game/bots/generate_strategies.py` です。

## ボットを登録して選択画面を使う

以下はリポジトリ直下で実行します。同名の登録は上書きせず拒否します。

```sh
game/build/paint-bots register explorer-h game/build/explorer-h.bin
game/build/paint-bots register raider-v game/build/raider-v.bin
game/build/paint-bots menu
```

画面に表示された番号を2〜4個入力し、参加者を確認して `y` で開始します。
試合後はEnterで選択画面へ戻り、`q` で終了します。
登録したファイルは `registered/` に保存されます。

## 構成と実機向け手順

- `vm/`：VM、アセンブラ、VM単体のサンプル
- `game/`：ゲームホスト、端末表示、ボット登録・選択、テスト
- `game/bots/`：ボットのアセンブリと生成スクリプト
- `game/bot_runner.c`・`.h`：両ゲーム共通のVM実行処理
- `treasure/`：宝取り競争、専用ボット、検証コード
- `maze/`：人がキーで操作する迷路、端末入力・描画、検証コード
- `dotchase/`：VMで動くDot Chase、生成元・アセンブリ・検証コード
- `console/`：共通メニュー、検証コード、実機への配置・起動設定ツール
- [ゲーム機の開発ロードマップ](game-console-roadmap.md)
- [共通メニュー版の実機配置・自動起動・復元](console/DEVICE.md)
- [ボットの転送・登録](game/REGISTRATION.md)
- [選択画面と実機の自動起動](game/APPLIANCE.md)
- [ログ・バックアップ・性能測定](game/MAINTENANCE.md)

自動起動・ログ管理ツールとsystemd設定は、サンプル環境
（ユーザー `pi`、配置先 `/home/pi/paintbot-vm`）を対象としています。
別の環境では設定と管理スクリプトの確認・変更が必要です。
まず上記の手動対戦で動作を確認してください。

`game/` の自動起動手順は従来のペイント合戦単独構成を対象とします。共通メニューへの切り替えは `console/DEVICE.md` を参照してください。`game/backup_appliance.py` は従来のペイント合戦の保守用で、共通メニュー・宝取り競争・迷路を含む全体バックアップではありません。
転送手順のSSH接続先 `pi@raspberrypi.local` は、利用する実機のユーザー名とホスト名に置き換えます。

## テスト

VM・3本のゲーム・共通メニューをまとめて確認する場合は、リポジトリ直下で実行します。

```sh
make test
```

観戦を含むため数分かかります。実機用ツールは次の模擬検証で確認でき、SSHやサービス設定の変更は行いません。

```sh
python3 -B console/test_device_stage5.py
python3 -B console/test_device_menu_service.py
```

ペイント合戦の個別テストは、ビルド後に次のように実行できます。

```sh
make -C game test test-host test-display
python3 game/test_bot_mode.py
make -C game test-multi test-strategies test-registry
```

観戦・選択画面のテストは疑似端末を使い、実時間の待機を含みます。
実機管理のテストは模擬環境を使い、実際のサービス設定は変更しません。

```sh
make -C game test-watch test-menu test-menu-service test-maintenance
```

## ライセンス・参考資料

MIT License。詳しくは [LICENSE](LICENSE) を参照してください。
取り込んだVMのライセンスは [vm/LICENSE](vm/LICENSE)、参考資料は
[vm/ATTRIBUTION.md](vm/ATTRIBUTION.md) にも記載しています。
