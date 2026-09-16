# T10: 刑事訴訟法203条・205条の限定的な数値期限診断

このpackは、刑事訴訟法203条・205条に現れる三つの数値期限を、有限個の時刻例について機械的に再生する趣味の検証例です。法的な適法・違法、勾留の可否、個別事件の結論は出しません。自然言語から形式モデルへの意味的な変換が正しいことも証明しません。

対象は2026年8月13日施行の改正状態 `323AC0000000131_20260813_508AC0000000067` です。保存済みe-Gov XMLから55条、203条、204条、205条、206条を抽出したsource bundleを使い、5件すべてに手作業のcoverage判定を残しています。

## 形式化した範囲

| 診断ID | 起点 | 期限内の行為 | 上限 |
|---|---|---|---:|
| `A203_SEND_48H` | 身体拘束 | 送致の手続 | 48時間 |
| `A205_RECEIPT_24H` | 検察官による受取 | 勾留請求または公訴提起 | 24時間 |
| `A205_RESTRAINT_72H` | 身体拘束 | 勾留請求または公訴提起 | 72時間 |

送致の手続と検察官による受取は別イベントです。205条の24時間上限と72時間上限も別々に評価するため、一方だけ超過する例を保持しています。勾留請求と公訴提起は`any-of`です。

時刻は `(tick, phase)` で表し、`tick` の単位をhourと宣言しています。`observation_end` はexclusiveです。包括期限が `(48, 0)` の場合、イベントなしで観測終端が `(48, 0)` なら`pending`、`(48, 1)`なら`violated_missing`です。これは有限離散モデルであり、連続時間や実際の時刻計算全般を網羅しません。

## 機械診断と限界

`binding.json` の `pack_diagnostics` は独立checkerがcertificateとreviewから再構成します。

独立checkerはcertificateの13 contextをすべて走査し、context名を発火条件にせず、再生されたnorm statusとeventから次を導きます。

- `SELECTED_TEXT_RELEASE_TRIGGERED`: 203条は`A203_SEND_48H`が`violated_late`または`violated_missing`なら出します。205条は`A205_RECEIPT_24H`または`A205_RESTRAINT_72H`の一つ以上が同じ二状態なら出します。遅れて行為が記録された場合も、選択した条文上の両制限内行為ではないという限定診断になります。
- `RELEASE_OBSERVED`: fixtureに釈放イベントが記録されていることだけを表します。前項のtriggerと実際の釈放完了を同一視しません。
- `ARTICLE_206_ASSESSMENT_UNRESOLVED`: 206条の事情説明イベントがあれば出します。数値triggerと併記し、やむを得ない事情、疎明、裁判官の判断は未解決のまま、数値期限超過を自動的に延長・消去しません。

203条・205条の告知、弁解、留置の必要性などは未形式化です。204条はout of scopeです。55条は時間で計算する期間を即時から起算する点だけを利用します。刑事訴訟法56条や刑事訴訟規則66条等の一般的延長との適用関係も未解決です。2027年3月31日施行予定の未施行改正 `323AC0000000131_20270331_507AC0000000039` が施行された時点で、このpackは再確認が必要です。

## 証拠のつながり

`task.json` → `candidate.json` → `review.json` をhashで結び、さらにsource spec、source-unit manifest、source bundle、`model.json`、`certificate.json`を`binding.json`へ結合しています。5つのsource unitについて、unit ID、構造path、全文quote、text hash、coverageを独立checkerがsource bundleから再構成します。

検証結果名は `MANUAL_MODEL_BINDING_VERIFIED` です。これは保存した出典・手作業候補・手作業レビュー・有限モデル・certificateが同じchainに属することを示します。semantic loweringや法的正確性を保証する結果名ではありません。

外部アンカー:

- source bundle: `6c8510b9c9022c6d4974bd1cc00fffdcd85b1ca4547f1027c644b68c5dc9a7fe`
- model: `e255570d7ff365b4c79afbbcdf2a65bb7e036ee9b10fa507216579560a192f6f`
- certificate: `a4e62ff42528c1abe55d4635f7ec3a85019a6fa39b45a47715cf824e647d62b3`
- binding: `e76cf9be471e45a5f83cb35083c15470f8f4ff3be6c1424ad3e97aec3b126811`

## 再検証

repository rootで実行します。

```bash
python3 -m procedurekernel verify \
  examples/procedures/t10-criminal-procedure-203-205/model.json \
  examples/procedures/t10-criminal-procedure-203-205/certificate.json \
  --expected-certificate-sha256 a4e62ff42528c1abe55d4635f7ec3a85019a6fa39b45a47715cf824e647d62b3 \
  --json
```

検出事項を含むため、このコマンドは`VERIFIED`を出しつつ終了コード1です。

```bash
python3 -m procedurekernel.t10_binding_cli \
  examples/procedures/t10-criminal-procedure-203-205/task.json \
  examples/procedures/t10-criminal-procedure-203-205/candidate.json \
  examples/procedures/t10-criminal-procedure-203-205/review.json \
  examples/procedures/t10-criminal-procedure-203-205/model.json \
  examples/procedures/t10-criminal-procedure-203-205/certificate.json \
  examples/procedures/t10-criminal-procedure-203-205/binding.json \
  examples/sources/criminal-procedure-55-203-206/source-spec.json \
  examples/sources/criminal-procedure-55-203-206/bundle \
  --expected-binding-sha256 e76cf9be471e45a5f83cb35083c15470f8f4ff3be6c1424ad3e97aec3b126811 \
  --json
```

独立checkerがsource packageとprocedure certificateをオフライン再生し、全chainを再構成できれば終了コード0になります。
