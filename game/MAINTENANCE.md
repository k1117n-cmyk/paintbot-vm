# 専用機のログ・バックアップ・測定

段階8の運用手順。実機は `/home/pi/paintbot-vm`、systemd 257、SSHユーザーnoi。
試合をしていない状態でMacからSSH接続し、プロジェクト直下で操作する。
サービスの再起動は選択画面をいったん閉じる。OSの再起動は行わない。

## ゲームのログ量を制限する

`manage_logging.py check` は初回適用前の構成確認。`install` はsudoが必要で、
ゲーム専用の次の2ファイルだけを追加する。既存ファイル・別のdrop-inがあれば停止する。

- `/etc/systemd/system/paintbot-menu.service.d/80-paintbot-logging.conf`
- `/etc/systemd/journald@paintbot.conf`

```sh
python3 game/manage_logging.py check
sudo python3 game/manage_logging.py install
```

stderrを専用journal namespace `paintbot` に分離し、選択画面サービスを一度再起動する。
画面の出力先はtty1のまま。試合は自動開始しない。
OS全体のjournal・SSH・アカウント・getty設定と元のサービス本体は変更しない。
診断保存量の目安は50MiB、1ファイル8MiB、保持7日、日単位でもファイルを回転する。
活動中のファイルは削除対象外なので、50MiBは厳密なディスク割当上限ではない。
OS自身の起動/サービス管理ログ、SSHからの検証ログ、バックアップはこの容量とは別。

適用は一時ユニットから専用journalへ1メッセージを書き、読取・整合性を確認する。
`LOG_SETUP_EXIT=0`、`LOG_SETUP_BACKUP=`、`LOG_RESTORE_COMMAND=`を保存する。
途中失敗時は元の選択画面へ戻す。復元にも失敗した場合はrecovery-requiredを記録して停止する。

適用後の確認とログの表示:

```sh
sudo python3 game/manage_logging.py status
sudo journalctl --namespace=paintbot -u paintbot-menu.service --no-pager -n 50
sudo journalctl --namespace=paintbot --disk-usage
```

ログ分離を取り消すには、適用時の実際のバックアップパスを指定する。

```text
sudo python3 game/manage_logging.py restore /var/lib/paintbot-menu/logging-実際の名前
```

自分で追加した2ファイルが元の内容と一致する場合だけ削除し、元の選択画面へ戻す。
バックアップと既に保存したjournalデータは削除しない。
通常gettyに戻す場合は、この取り消しを終えてからAPPLIANCE.mdの元の自動起動復元コマンドを使う。

## 手動バックアップと別フォルダでの復元

sudoを付けずに実行する。

```sh
python3 game/backup_appliance.py create
```

登録ボット、game/vmのソース・手順書、インストール済みの専用サービス本体と
ログ分離用2設定を保存する。build・incoming・ログ・OS/SSH設定・過去のバックアップは含めない。
1ファイルが大きすぎる場合、無効な登録名、リンクや読み取り中の変更があれば停止する。
1世代64MiB以内、ツールで作成したアーカイブは最大5世代。既存世代は自動削除しない。
上限に達したら、Mac等にコピーして検証済みの世代をどれだけ残すか、操作者が判断する。

出力の`BACKUP_PATH`、`BACKUP_SHA256`、`BACKUP_BYTES`を保存する。
Macにもscpでコピーし、同じSHA-256になることを確認する。保存は`~/paintbot-backups`。

復元先は存在しないフォルダを指定する。アーカイブを全検証してから作成し、
元の登録ディレクトリや/etcを上書きしない。不正パス・リンク・改変・非対応圧縮を拒否する。

```text
python3 game/backup_appliance.py verify /home/pi/paintbot-backups/実際の名前.zip
python3 game/backup_appliance.py restore /home/pi/paintbot-backups/実際の名前.zip /home/pi/paintbot-restored-新しい名前
```

復元先の`project/`に登録とソース、`system/`にサービス設定が入る。
復元途中のI/O失敗では`.restore-incomplete`を残す。そのフォルダを本番に使用しない。
復元後に`project/`でVMとゲームをビルドし、VMセルフテストと登録済みボットの対戦を確認する。

```sh
make -C vm
make -C game
vm/build/handmade-vm --self-test
game/build/paint-bots match --no-watch explorer-h raider-v
```

本番のプロジェクトを失った場合は、`/home/pi/paintbot-vm`が存在しない状態で
別フォルダへ復元した`project/`をその場所へ配置して再ビルドする。
サービスが未導入なら元のmanage_menu_service.pyの確認/導入、その後manage_logging.pyを使う。
`system/`に復元した設定は参照・照合用で、自動で/etcへコピーしない。
稼働中の本番への切替や既存ファイルの削除は、この復元試験には含めない。

## 性能と100ms期限の確認

```sh
python3 game/benchmark_appliance.py /home/pi/paintbot-benchmark-新しい名前
```

同じディレクトリへ上書きしない。2/3/4体を各3試合、2/4体の64桁×24行の疑似端末観戦を各1試合、
ビルドや他の試合と並行させず逐次実行する。観戦は各40秒以上かかる。
参加順はexplorer-h・raider-v・explorer-v・raider-hの先頭から参加数分。
測定はbuildのバイトコードを使い、実機の登録済み版との一致は反映手順で別途確認する。

`results.json`と全試合のstdout/stderrを保持する。時間はホスト全体の起動から終了まで、
CPU時間と最大RSSはwait4が返す子ホスト/その子プロセスの値。RSSは合計常駐量ではない。
観戦は読み取り側のスケジューリングも含むため、観測した最短画面間隔を厳密な表示周期とは扱わない。
CPU数、負荷、メモリ、温度、CPU周波数/ガバナーも取得できた範囲で記録する。

`BENCHMARK_COMPLETE=1`は測定予定の試合が完走した意味。
`BENCHMARK_ALL_HEALTHY=1`は全6,600応答が期限内の正常応答だった意味。
異常が出てもその結果を残し、成功するまで測り直さない。試合の中断や測定上限での停止も記録する。
100msは変更しない。結果は試験したボットと負荷条件の観測であり、未知のボット/負荷を保証しない。
Macで過去と今回の復元試験に発生した自然なtimeoutの原因を解消したとは扱わない。

### Zero 2 Wでの測定結果（2026-11-26）

Raspberry Pi Zero 2 W上で、上記の条件で測定した結果。測定環境はRaspberry Pi OS Lite 32-bit、
armv7l、Linux `6.18.50+rpt-rpi-v7`、Python `3.13.5`、CPU4個、governor `ondemand`。
測定時刻は2026-11-26 02:58:28〜03:00:31 UTC。
測定ツール `game/benchmark_appliance.py` のSHA-256は
`4a913fc6ef7b0129597175de86a002f4a05ec3c767b05f2ca3ec35e566032af1`。

| 条件 | 試合数 | 所要時間の範囲（秒） | 中央値（秒） |
| --- | --- | --- | --- |
| 2体・非観戦 | 3 | 2.960〜3.163 | 3.160 |
| 3体・非観戦 | 3 | 4.736〜4.768 | 4.765 |
| 4体・非観戦 | 3 | 6.358〜6.363 | 6.362 |
| 2体・観戦 | 1 | 40.172 | — |
| 4体・観戦 | 1 | 40.177 | — |

結果JSONでは `measurement_complete=true`、`all_healthy=true`。
全11試合が終了コード0で200ターンを完走し、6,600応答すべてが正常だった。
timeout・invalid・VM-errorは各0回、測定上限による停止もなかった。観戦は各201画面を回収した。

観戦には1ターン約200msの表示待ちが含まれるため、非観戦との差を描画処理の負荷とは扱わない。
観戦の時間は64桁×24行の疑似端末で出力を回収したホストの実行時間であり、
モニターを撮影して測った時間ではない。
この4体と測定時の負荷条件での結果で、任意のボットや負荷での100ms以内の応答を保証しない。
Macでの既知の自然発生timeoutの原因解消を示す結果でもない。

## ローカルの保守ツール検証

`make -C game test-maintenance`でログ設定の模擬適用/復元、バックアップ/復元と再ビルド、
測定パーサとwait4/PTYを確認する。模擬systemdは実機の設定検証の代用ではない。

設定の根拠（systemd 257）:
[namespace](https://www.freedesktop.org/software/systemd/man/257/systemd.exec.html#LogNamespace=)、
[保存容量と保持期間](https://www.freedesktop.org/software/systemd/man/257/journald.conf.html)。
