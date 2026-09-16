# T12 compact decision証拠 検証記録

2026-09-16。境界値同値類、strict JSON Lines、逐次commitment、独立checkerを `finite-decisions/1` の基礎 `check` へ実装した時点の記録。仕様は[compact decision証拠 v0.1](compact-certificate-v0.1.md)、計画全体は[T12設計](../planning/t12-evidence-scaling.md)を参照する。

これはT12全体の完了記録ではない。`diff`、`reachability`、norm、procedureの証拠圧縮と、体系的な時間・peak allocation再測定は未実装である。

## 保存したclub20証拠

Python 3.14.4、WSL Ubuntuで、リポジトリ直下から次を実行した。二つの `check` は保存先がまだ存在しない状態で実行した。

```bash
python3 -m compactkernel estimate examples/club20/broken.json --json
python3 -m compactkernel estimate examples/club20/fixed.json --json
python3 -m compactkernel check examples/club20/broken.json \
  --certificate examples/club20/broken.compact.jsonl --json
python3 -m compactkernel check examples/club20/fixed.json \
  --certificate examples/club20/fixed.compact.jsonl --json
python3 -m compactkernel verify examples/club20/broken.json \
  examples/club20/broken.compact.jsonl \
  --expected-certificate-sha256 1ac37d4180f1ea16a16e4c900f356070e3c756233cfadf1cd650318102b7e18f --json
python3 -m compactkernel verify examples/club20/fixed.json \
  examples/club20/fixed.compact.jsonl \
  --expected-certificate-sha256 dff0123181c20d6df46bd3b9662c378352796b44404fe32b49fa90dd63c3c8b8 --json
```

| 項目 | 問題版 | 修正版 |
|---|---:|---:|
| 具体状況 | 416 | 416 |
| 境界セル | 80 | 64 |
| JSONL行数 | 82 | 66 |
| 生成前の保証下限 | 28,903 bytes | 23,443 bytes |
| compact証拠 | 35,360 bytes | 28,309 bytes |
| 旧全数証拠 | 89,654 bytes | 89,423 bytes |
| 旧全数証拠からのbytes減少 | 60.56% | 68.34% |

保存証拠とSHA-256:

- [broken.compact.jsonl](../examples/club20/broken.compact.jsonl): `1ac37d4180f1ea16a16e4c900f356070e3c756233cfadf1cd650318102b7e18f`
- [fixed.compact.jsonl](../examples/club20/fixed.compact.jsonl): `dff0123181c20d6df46bd3b9662c378352796b44404fe32b49fa90dd63c3c8b8`

両方とも外部expected hash付きの別 `verify` で `VERIFIED` になった。問題版は資格衝突32件、料金gap32件、貸出上限衝突4件で、最初のwitness indexはそれぞれ288、288、404。修正版は全11照会が0件だった。件数とwitnessは旧全数証拠と一致した。

## T06容量境界との比較

歴史的T06入力 `check-first-failure-05662.json` は、100個の常時成立規則と整数 `case_id=0..5661` を持つ。既存 `rulekernel check` は従来どおり `LIMIT_REACHED: Evidence exceeds 8 MiB; no complete result` になった。同じモデルをcompact経路へ渡すと、規則が整数値を参照しないため5,662状況が1セルになった。

```bash
python3 -m compactkernel check \
  benchmarks/t06/results/boundary-endpoints/check-first-failure-05662.json \
  --certificate /tmp/rule-formalization-t12-check-first-failure-05662.jsonl --json
python3 -m compactkernel verify \
  benchmarks/t06/results/boundary-endpoints/check-first-failure-05662.json \
  /tmp/rule-formalization-t12-check-first-failure-05662.jsonl \
  --expected-certificate-sha256 fe75a0d2672fdb8ac7fae1ae4a2a77128773628517a3e5c966ffca42decd5662 --json
```

結果は1セル、3行、2,971 bytes、SHA-256 `fe75a0d2672fdb8ac7fae1ae4a2a77128773628517a3e5c966ffca42decd5662`、全10 conflict照会0件で `VERIFIED`。生成・生成直後の独立検査・公開までの一回の実測は1.76秒だったが、正式な反復benchmarkではなく参考値である。この一時証拠はrepositoryへ保存していない。

旧T06 reportは変更せず、次の外部anchorで再検査して `VERIFIED`、27 workflow、13 `LIMIT_REACHED` workflowのままである。

```bash
python3 -m benchmarks.t06.report_checker benchmarks/t06/results/2026-09-15.json \
  --expected-report-sha256 6bda457de5e19dbcbd74bb7df50f528b1c4dd6ca1e1040a972af35c7d3af1068
```

この比較は、整数境界の少ないfamilyで証拠bytesを減らせることを示す。T06の13 Bool静的matrixは整数境界でまとまらず、8,192セルのままである。したがって一般の高速化や処理可能規模を示す値ではない。

## 負例と独立性

専用テストでは次を確認した。

- 小さいモデルで、旧全数経路と全照会件数・witnessが一致する。
- 比較の向き、`lt/le/gt/ge/eq/ne`、facts、領域端、符号付き64 bit最大値から正しいcutを導く。
- 整数変数同士の比較では単一値セルへfallbackする。
- cellの重みとvirtual commitmentの改変、trailer欠落、recordの複製・並替え・余分な末尾、CRLF、非canonical JSON、外部anchor不一致を拒否する。
- 保証下限が上限を超える場合は意味評価前に停止し、生成中はrecord追加前の正確なbytes上限で停止する。
- `check` の失敗時に部分証拠を公開せず、既存出力を置換しない。
- checker sourceがcompact producer、共通partition planner、旧全数engineをimportしない。
- producerとcheckerのpartitionを同じ誤った1セルへ変異させても、checker自身の全具体case集計とwitnessが重み付きセル集計に一致せず拒否する。
- 出力公開との競合では相手のfileを保持し、一時fileの削除失敗では公開linkを同じinodeか確認して巻き戻し、元のI/O errorを保持する。

実行したcompact専用テストは次の28件で、全件合格した。T12で変更したnorm/procedure/T10 binding CLIとprocedure増分上限を含む集中テスト84件、全回帰397件も合格した。

```bash
python3 -m unittest \
  tests.test_boundary_partition \
  tests.test_compact_kernel \
  tests.test_compact_cli -v
```

具体状況10,000と証拠8 MiBのhard capは維持している。virtual case commitmentのためproducerとcheckerは全具体状況を逐次再評価し、実行時間は全積に依存する。Python heapの厳密な上限、OS kill時のexit 2、意味論の機械証明はこの検証に含まれない。
