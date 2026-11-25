# paintbot-vm

![Language: C](https://img.shields.io/badge/Language-C-00599C)
![Tools: Python 3](https://img.shields.io/badge/Tools-Python%203-3776AB)
![Tested on: Raspberry Pi Zero 2 W](https://img.shields.io/badge/Tested%20on-Raspberry%20Pi%20Zero%202%20W-A22846)
![Tested on: macOS](https://img.shields.io/badge/Tested%20on-macOS-555555)
[![License: MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)

自作VM上で動くボット同士が、16×16マスの盤面を塗り合う対戦ゲームです。
C言語で実装したVM・アセンブラ・ゲームホストと、アセンブリで書いたボットを収録しています。
Raspberry Pi Zero 2 W（Raspberry Pi OS Lite 32-bit）で動作を確認しています。
macOSでもビルドして対戦を試せます。

プレイヤーはボットのプログラムを作り、2〜4体を選んで対戦を観戦します。
方向キーでボットを直接操作するゲームではありません。

## 必要なもの

- Cコンパイラ（`cc`）と `make`
- Python 3（テスト、ボットのソース生成、実機管理ツール用）
- 観戦表示にはANSIカラー対応の端末（64桁×24行以上）

通常の対戦には外部の描画ライブラリやPythonパッケージは必要ありません。
自動起動やログ管理には、別途systemdを使います。

## ビルドして対戦する

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
- [ボットの転送・登録](game/REGISTRATION.md)
- [選択画面と実機の自動起動](game/APPLIANCE.md)
- [ログ・バックアップ・性能測定](game/MAINTENANCE.md)

自動起動・ログ管理ツールとsystemd設定は、サンプル環境
（ユーザー `pi`、配置先 `/home/pi/paintbot-vm`）を対象としています。
別の環境では設定と管理スクリプトの確認・変更が必要です。
まず上記の手動対戦で動作を確認してください。
転送手順のSSH接続先 `pi@raspberrypi.local` は、利用する実機のユーザー名とホスト名に置き換えます。

## テスト

ビルド後、リポジトリ直下で順に実行します。

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
