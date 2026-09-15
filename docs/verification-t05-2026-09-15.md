# T05 手書き解釈IR検証記録

実施日: 2026-09-15。対象: [手書き解釈IRとCore変換 v0.1](interpretation-ir-v0.1.md)。これは、固定入力からCore・来歴・host gold例を再構成した記録である。架空原文の読み方が正しいこと、法律専門家が承認したこと、一般の日本語を正しく形式化できることの証明ではない。

## 実装した経路

- 厳密なtask/candidate/review/scope expectations検査、依存gate、変換定義: [`interpretation_model.py`](../rulekernel/interpretation_model.py)
- candidateから既存Coreと外側packageを作るproducer: [`interpretation.py`](../rulekernel/interpretation.py)
- producerをimportせずCore・来歴・review summary・packageを再構成するchecker: [`interpretation_checker.py`](../rulekernel/interpretation_checker.py)
- `compile-interpretation`、`verify-interpretation`: [`__main__.py`](../rulekernel/__main__.py)

埋込Coreは既存カーネルとの互換性のため`finite-decisions/1`、`origin_kind=authored_core`のまま。原文由来であることは外側の`rule-interpreted-core-package/1`、`origin_kind=interpreted_source`、bindings、provenance、scope expectationsに保持する。Core単体を切り離した場合は解釈review済みと扱えない。

## 保存fixture

保存先: [架空会員規約の手書き解釈](../examples/interpretations/member-eligibility/README.md)

| 項目 | 固定値・結果 |
|---|---|
| source units | 2 |
| manifest reference | resolved 1件: 第2条の「前条」から第1条 |
| Core rules | decision 1件、replacement exception 1件 |
| 宣言Cartesian積 | 104状況 |
| 背景制約後 | 78状況 |
| host semantic tests | 5件 |
| coverage | selected 2 / unresolved 0 / excluded 0 |
| source bundle hash | `a63021f7766381a75a7cb8b91f285f47122c1f5d3912a2f6132653e91cf4ac32` |
| source unit manifest hash | `800acf9358ff61cf7aecac2e433a011e4eb4bce400b5b23e5ac11c88757f0531` |
| task hash | `27d0f6dfceed5dd86c8bdc6392760e0e5f47b8bdc5165ec1ddbeda13f24dfe16` |
| candidate hash | `2248de5a76bb7ed143cd35b656c653c8d8548ad49d40eae11cda670943fd622d` |
| review hash | `e5e7f865b2195b64057842c70e25b4a78755e1fbaf82061df6c8e64504ad88a0` |
| interpretation snapshot hash | `d761f9440b80e8c5643c1df6e7ac9e53914370874240c1ccf26828dfed892d4b` |
| scope hash | `184a90740204736f0263e9e0365212f9e2a2d5ee6c4e5ff560d8c0a916224a68` |
| scope expectations hash | `51dc9ee5f607d6b93d100872b7f3e38b6fe320440c875780a84d47b47575f5a8` |
| Core model hash | `b34744e3ea2d98f73d04d8eef9d5867f8d2a553f67bff50f22369c848e50b6e5` |
| compiled package hash | `25b6fd536726dce2420f49776e961cb8bb0b78d41b1b8865608dd0fc2335a112` |

保存reviewの`review_method=manual_fixture_review`はCodexが開発用goldを作った記録である。ユーザーや法律専門家による承認ではなく、reviewer本人性や時刻を署名で証明するものでもない。

## 生成とoffline再検査

新しい`/tmp`出力へ次を実行した。

```bash
python3 -m rulekernel compile-interpretation \
  examples/interpretations/member-eligibility/task.json \
  examples/interpretations/member-eligibility/candidate.json \
  examples/interpretations/member-eligibility/review.json \
  examples/interpretations/member-eligibility/scope-expectations.json \
  --source-spec examples/sources/member-eligibility/source-spec.json \
  --source-bundle examples/sources/member-eligibility/bundle \
  --expected-source-bundle-sha256 a63021f7766381a75a7cb8b91f285f47122c1f5d3912a2f6132653e91cf4ac32 \
  --expected-review-sha256 e5e7f865b2195b64057842c70e25b4a78755e1fbaf82061df6c8e64504ad88a0 \
  --expected-scope-expectations-sha256 51dc9ee5f607d6b93d100872b7f3e38b6fe320440c875780a84d47b47575f5a8 \
  --package /tmp/member-eligibility-doc-verify-20260915.json \
  --json
```

exit 0で`LOWERING_VERIFIED`、`HOST_REVIEW_RECORDED`、2 rules、5 semantic tests、coverage selected 2/unresolved 0/excluded 0を返した。source bundle、review、scope expectationsの外部anchorは全てtrue。生成packageは保存済み`compiled.json`とbyte-for-byte一致し、SHA-256は`25b6fd536726dce2420f49776e961cb8bb0b78d41b1b8865608dd0fc2335a112`だった。確認後、`/tmp`の生成物は削除した。

保存済みpackageには、さらに外部package hashを指定して再検査した。

```bash
python3 -m rulekernel verify-interpretation \
  examples/interpretations/member-eligibility/task.json \
  examples/interpretations/member-eligibility/candidate.json \
  examples/interpretations/member-eligibility/review.json \
  examples/interpretations/member-eligibility/scope-expectations.json \
  examples/interpretations/member-eligibility/compiled.json \
  --source-spec examples/sources/member-eligibility/source-spec.json \
  --source-bundle examples/sources/member-eligibility/bundle \
  --expected-source-bundle-sha256 a63021f7766381a75a7cb8b91f285f47122c1f5d3912a2f6132653e91cf4ac32 \
  --expected-review-sha256 e5e7f865b2195b64057842c70e25b4a78755e1fbaf82061df6c8e64504ad88a0 \
  --expected-scope-expectations-sha256 51dc9ee5f607d6b93d100872b7f3e38b6fe320440c875780a84d47b47575f5a8 \
  --expected-package-sha256 25b6fd536726dce2420f49776e961cb8bb0b78d41b1b8865608dd0fc2335a112 \
  --json
```

exit 0。4種類の外部anchorは全てtrue、`offline=true`だった。

## テストと負例

実行結果:

```text
python3 -m unittest tests.test_interpretation tests.test_interpretation_cli -q
Ran 46 tests ... OK

python3 -m unittest discover -s tests -q
Ran 205 tests ... OK

python3 -m compileall -q rulekernel tests
exit 0
```

T05の46件は主に次を固定する。

- 保存packageのbyte-for-byte再構成、既存Coreカーネルとのmodel hash join、外側と埋込Coreのorigin境界、manifest全文・span由来provenance。
- candidateの提案testをhost goldとして使わないこと。候補による承認・scope期待の自己申告、pending/rejected/stale review、未採用assumption、必要条件、未対応の規範kindを拒否。
- source unitの引用・manifest coverage・referenceの欠落/付替え、未選択override target、選択issue、未解決referenceを直接または未選択dummy経由で隠す経路を拒否。
- 閾値、結論の否定、必要条件と十分条件、exception欠落の既知変異をhost gold例で`SEMANTIC_MISMATCH`にする。
- review、scope expectations、packageの外部anchor、Core、provenance span/unit、埋込scope、変換定義、package shapeの改ざんを拒否。
- checker成功前の非公開、既存destination非上書き、source bundle内への出力拒否、失敗時に部分packageを残さないCLI挙動。
- enum位置へ配列等を置くJSONを未処理`TypeError`にせず、構造化した`UNSUPPORTED`としてexit 2で拒否。

実装中の敵対的レビューでは、同じsource unitの未解決referenceを未選択dummy provisionへ移すと選択ruleだけを確定できる経路を発見した。選択したunitは、そのunitを起点にする全issue/referenceを継承し、resolved referenceも選択provisionと選択先へ接続するよう修正した。直接参照とdummy逃がしの両方を固定回帰にした。

追加の一時監査では、各入力JSONの各階層ノードを`null`、`true`、`0`、空文字列、空配列、空objectへ一箇所ずつ置換し、依存hashを可能な範囲で再結合してcompile/verifyを2,456回呼んだ。`KernelError`以外の未処理例外は0件。この監査スクリプトは実行後に削除しており、保存fixtureでも継続回帰でもない。上の46件・205件には含めていない。

## 残る境界

- `LOWERING_VERIFIED`は、固定入力に対するCore・来歴・具体例の再構成成功を表す。原文の意味を自動証明しない。
- host gold例は既知の否定・境界・必要十分・例外変異を検出する。日本語一般の意味lintや解釈候補の網羅性を保証しない。
- source bundle、review、scope expectations、packageの外部hashを同じ主体が同時に書き換えられる保存方法では、真正な過去状態を証明できない。reviewer署名・第三者timestampは未実装。
- candidateとhost入力は分離したが、保存fixtureのreviewは独立した人の確認ではない。実法令の意味対応へ使う前に、対象分野のレビュー記録が必要。
- checkerはproducerをimportしないが、validator、JSON/hash、Python処理系は信頼対象として共有する。checker自体の健全性を機械証明していない。
- v0.1の変換対象は有限の定数decisionとreplacement exceptionだけ。義務・禁止・許可・期限・裁量、部分source unitの独立レビュー、LLM候補生成は未実装。
- T05はscope expectationsを固定するまで。到達可能性の段階件数との一致、期待内inactiveの情報扱い、stale・未指定の診断は[T03.1](verification-t03.1-2026-09-15.md)で別証拠として実装した。T03.1はこのT05 chainを再構築しないため、原文からの検査では両経路を併用する。
