# 盤面を広く使う対戦用ボット

`explorer-h`・`explorer-v`・`raider-h`・`raider-v`を用意した。
左右へ進むだけの従来サンプルと違い、盤面と自分の位置を読み、上下左右へ移動して塗る。
ゲームは従来どおり16×16、200ターン、2〜4体。各ボットを観戦して対戦させる方式で、
プレイヤーが方向キーで直接動かす方式ではない。

| 名前 | 隣接マスを選ぶ優先順位 | 同じ優先度のときの基本経路 |
| --- | --- | --- |
| explorer-h | 未塗装 → 相手の色 → 自分の色 | 横方向に折り返して巡回 |
| explorer-v | 未塗装 → 相手の色 → 自分の色 | 縦方向に折り返して巡回 |
| raider-h | 相手の色 → 未塗装 → 自分の色 | 横方向に折り返して巡回 |
| raider-v | 相手の色 → 未塗装 → 自分の色 | 縦方向に折り返して巡回 |

優先する色が隣接マスにあると巡回経路から外れて取りに行く。
移動先が全部自分の色なら全256マスを巡る経路に沿って進み、端で止まり続けない。
局所的な判断なので常に最善手を選ぶわけではない。同じ組合せとID順では同じ展開になる。
番号の順番を変えると開始位置が変わり、展開も変わる。相手の色の上書きでは
自分の得点が増えると同時に相手の得点が減る。

## 10インチの選択画面で遊ぶ

実機に4体を追加した後、選択画面で `r` を押すと新しい名前が表示される。
登録名の名前順なので、従来の番号から変わることがある。画面に出た名前を見て選ぶ。
既存のmini-right・air-left・wait系も残すが、広く盤面を使う対戦には新しい4体を選ぶ。

- まず2体: explorer-h、raider-vの番号をこの順に入力し、`y`で開始。
- 4体: explorer-h、raider-v、explorer-v、raider-hの番号をこの順に入力し、`y`で開始。
- 試合後はEnterで選択へ戻る。次は同じ2体の番号を逆順にして、開始位置を入れ替えてみる。

SSHから試合を実行すると画面はSSH元に出る。10インチで見る場合は10インチの選択画面から始める。

## ビルドと登録

プロジェクト直下で `make -C vm`、続いて `make -C game`。
小型アセンブラのMOV/DEC/ADD/SUBは、VMに元からある命令の表記。
VM本体と命令の動作、100msの期限は変えていない。

実機でまだ登録していない場合だけ、実機のプロジェクト直下で実行する。
同名は上書きしないので、既に登録済みの場合は再実行しない。

```sh
game/build/paint-bots register explorer-h game/build/explorer-h.bin
game/build/paint-bots register explorer-v game/build/explorer-v.bin
game/build/paint-bots register raider-h game/build/raider-h.bin
game/build/paint-bots register raider-v game/build/raider-v.bin
```

ソースは `game/bots/*.asm`、共通の生成元は `game/bots/generate_strategies.py`。
再生成は `python3 game/bots/generate_strategies.py`。
検証はビルド後に `make -C game test-strategies`。全座標の巡回、色による判断、
全IDの入力、境界、実VMでの2・3・4体200ターン戦と縦横の塗装を確認する。
