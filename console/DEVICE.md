# 共通メニュー版の実機配置と自動起動

公開用の例はユーザー `pi`、接続先 `pi@raspberrypi.local`、既存の配置 `/home/pi/paintbot-vm` を想定します。開発者の実機で確認した3ゲーム版から、公開用にユーザーとパスを調整しています。この公開用設定での実機適用は未実施です。

通常の手動起動はリポジトリ直下で `make run` です。以下の配置ツールは、既存のpaintbot専用機と登録フォルダーがある環境へ、新しい共通メニュー版を別フォルダーに配置するものです。新規のOSへ自動起動環境を一括構築するツールではありません。

## 配置して検証する

Macのターミナルで、取得したリポジトリ直下から実行します。

```sh
python3 console/deploy_device.py --target pi@raspberrypi.local
```

接続先のホスト名は変更できます。ユーザーを変更する場合は、接続先だけでなく、スクリプト内の `/home/pi`、アカウント検査、サービス設定とその照合ハッシュも確認・調整する必要があります。

ツールはソースだけのパッケージとSHA-256一覧を作成し、`/home/pi/vm-game-console-stage5-一意のID/project` に新規配置します。VM・3本のゲーム・共通メニューをビルドし、判定・実VM対戦・観戦・迷路の即時キー入力／端末設定復元・メニュー復帰を検証します。既存の `/home/pi/paintbot-vm/registered` をリンクで参照し、検証前後で登録内容が変わらないことを確認します。サービス設定は変更しません。サービス情報の表示ではページャーを無効にして、対話端末でも検証を進めます。

成功時は `STAGE5_EXIT=0` と `DEPLOY_EXIT=0`、`PROJECT=` に配置先、`LOG=` にMac側の保存ログを表示します。失敗した場合はそこで停止し、ログと新フォルダーを残します。

SSHへ接続せずパッケージだけ用意する場合は、次のコマンドを使います。

```sh
python3 console/deploy_device.py --prepare-only
```

## 手動で画面を確認する

既存の対戦を終了してから、実機のモニターにつながった端末で、出力された `PROJECT` のフォルダーへ移動し、`console/build/game-console` を実行します。両ボット対戦ゲームの対戦と、迷路の移動・クリア・Qによるゲーム選択復帰を確認します。SSH端末での観戦を、実機モニターの表示確認とは区別してください。

## 自動起動を共通メニューへ切り替える

切り替えツールは、既存の `paintbot-menu.service` がこのリポジトリの設定と一致し、ログ設定 `80-paintbot-logging.conf` が適用済みで、サービスがactive/enabledである構成を対象とします。実機ビルド成功の記録と候補設定も検査します。異なる構成では停止します。照合を省略して実行しないでください。

次の操作はサービスを再起動するため、進行中の試合を終了してから行います。OSの再起動は行いません。実機で、配置ツールが表示した実際のPROJECTを使って実行します。

```sh
sudo python3 /home/pi/vm-game-console-stage5-実際のID/project/console/manage_device_menu.py install /home/pi/vm-game-console-stage5-実際のID/project
```

配置パッケージには適用ツールを含めないため、適用前にMacからこの公開版の `console/manage_device_menu.py` を、実際のPROJECTの `console/` へ転送してください。Macから転送と適用を続けて行う場合は、次の補助スクリプトも使えます。第2引数はPROJECTのフォルダー名に含まれる12桁のIDです。

```sh
sh console/activate_device.sh pi@raspberrypi.local 実際の12桁のID
```

適用時はサービス本体とログ設定、追加する候補設定、状態を `/var/lib/paintbot-menu/console-実際のID` に保存します。systemdの構文検証を行い、`90-game-console.conf` だけを追加して作業フォルダーと起動プログラムを変更します。サービス本体、ログ設定、SSH、getty、登録ボットは編集しません。

成功時は `CONSOLE_INSTALL_EXIT=0`、補助スクリプトはさらに `CONSOLE_ACTIVATE_EXIT=0` を表示します。同じ追加設定がすでにある場合は停止するため、適用済みの環境へ繰り返し実行しないでください。

## 元の自動起動へ戻す

実機で、実際のIDを使って実行します。

```sh
sudo python3 /home/pi/vm-game-console-stage5-実際のID/project/console/manage_device_menu.py restore /var/lib/paintbot-menu/console-実際のID
```

追加ファイルが作成時のままであることを確認し、そのファイルだけを取り消してサービスを再起動します。管理者による変更を検知した場合は停止します。実機での復元動作は開発者の環境でも未確認です。

## 適用後の確認

実機で両ボット対戦ゲームの対戦、迷路の操作、メニュー復帰を確認し、OS再起動後はサービスのactive/enabled、新しい作業フォルダー、`LogNamespace=paintbot`、モニター上のメニュー自動表示を確認します。開発者の元の環境では2ゲーム版の再起動後表示まで確認済みで、迷路の追加後はサービス再起動と実画面操作を確認しています。迷路追加後のOS再起動と、この公開用設定での実機適用は未実施です。

## ローカルの模擬検証

```sh
python3 -B console/test_device_stage5.py
python3 -B console/test_device_menu_service.py
```

前者はパッケージの検査と隔離配置でのビルド・対戦、後者は模擬systemdでの適用・復元と拒否条件を検証します。SSH、sudo、実際のサービス設定変更は行いません。
