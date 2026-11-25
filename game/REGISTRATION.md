# LAN内のボット登録と対戦（段階7）

Zero 2 Wの配置は `~/paintbot-vm`、接続先の例は `pi@raspberrypi.local`。
同じLAN内のMac miniとMacBook Airから、既存のSSHアカウントで転送する。
以下の接続先は実際のアドレスに合わせる。パスワードはSSHの入力欄にだけ入力する。

## 実機の準備

Zero 2 Wのプロジェクト直下で実行する。

```sh
cd ~/paintbot-vm
make -C vm
make -C game
mkdir -p incoming
```

`game/build/paint-bots` はプロジェクト直下から使う。
登録時に `incoming/` と `registered/` が無ければ作成する。
両ディレクトリの内容はGit管理しない。初版は登録を済ませてから試合を開始する。

## 各Macでボットを作る

各Macにこのプロジェクトの `vm/tools/small-asm.c` と使用するアセンブリを用意する。
まず `command -v cc` と `command -v ssh`、`command -v scp` で有無を確認する。
既存の開発ツールが使える場合の例（プロジェクト直下）：

```sh
make -C vm
vm/build/small-asm game/bots/right.asm /tmp/mini-right.bin
```

MacBook Airでは別のプログラムを用意する。例：

```sh
make -C vm
vm/build/small-asm game/bots/left.asm /tmp/air-left.bin
```

これはMac用の実行ファイルではなく、自作VMのバイトコードを作る操作。
Mac用のVM・アセンブラの実行ファイルはZero 2 Wへ転送しない。
開発ツールが無い端末では導入済みと扱わず、導入方法を別途確認する。

## 転送して登録する

Mac miniのターミナルで実行する。一意の転送先を作り、転送が完了してから登録する。

```sh
upload_dir=$(ssh pi@raspberrypi.local 'mkdir -p ~/paintbot-vm/incoming && mktemp -d ~/paintbot-vm/incoming/upload-XXXXXXXX')
scp /tmp/mini-right.bin "pi@raspberrypi.local:$upload_dir/bot.bin"
ssh pi@raspberrypi.local "cd ~/paintbot-vm && game/build/paint-bots register mini-right '$upload_dir/bot.bin'"
```

SSHとscpの各コマンドが成功したことを確認してから次へ進む。
MacBook Airでも同様に、ローカルのファイルを `/tmp/air-left.bin`、登録名を `air-left` として転送・登録する。
同じ名前は拒否されるので、再登録には `mini-right-v2` のような別名を使う。
登録後も転送元ファイルは残す。自動削除・上書きは行わない。

登録名はASCII英数字・ハイフン・アンダースコアの1〜32文字。先頭のハイフンは禁止し、先頭は英数字かアンダースコアとする。拡張子を付けずに指定する。
通常ファイルで1〜1,048,576 bytesのものだけ登録でき、シンボリックリンクは拒否する。
旧規則で先頭ハイフンの名前を登録済みの場合、その名前は一覧・試合から除外する。
ファイルは削除しないので、必要なら元の `.bin` を新しい適合名で登録する。
登録は内容のコピーを確定する操作で、ボットの正常動作を保証するものではない。
無限ループ・不正出力・VMエラーは既存ホストの100ms期限と異常時Xで扱う。

## 一覧・対戦

Zero 2 Wの10インチモニターに接続したターミナルで実行する。

```sh
cd ~/paintbot-vm
game/build/paint-bots list
game/build/paint-bots match --watch mini-right air-left
```

一覧は登録名の昇順。指定順がID順で、同じ登録名の重複指定は拒否する。
表示オプションは参加者名より前に最大1個指定する。不明なオプションは拒否する。
表示指定なしでは既存ホストの端末判定に従い、`--no-watch` で最終結果だけを出す。

4体戦では各Macからもう1つずつ別名で登録してから、例えば以下を実行する。

```sh
game/build/paint-bots match --watch mini-right air-left mini-wait air-wait
```

2体は `mini-right`＝ID 1、`air-left`＝ID 2。
4体はさらに `mini-wait`＝ID 3、`air-wait`＝ID 4。
両方のwaitボットは `game/bots/wait.asm` から各端末で作成できる。

## 検証と完了条件

ローカルの登録検証はビルド後に `make -C game test-registry` で実行する。
既存のゲーム・ホスト・表示・VM/統合・多体・観戦テストも回帰対象。
ビルドと試合は並行させず、失敗ログを消して成功扱いにしない。

段階7の完了には、実際にMac miniとMacBook Airそれぞれで用意したボットを登録し、
Zero 2 Wで200ターン対戦できた記録が必要。各端末での生成・登録のログと、実機の最終得点・
勝敗・各IDの正常/異常件数を残す。4体戦も確認する。
ローカルで別フォルダを使った検証を2端末由来の対戦とは扱わない。

上下左右へ動く対戦用の4体と選択画面での遊び方は [PLAYING.md](PLAYING.md) を参照。
従来のright/left/wait系は動作確認用として引き続き使える。
