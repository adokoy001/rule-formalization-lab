# T06 再現可能な合成ベンチマーク

T06は、自前カーネルの現在の全列挙方式について、モデル内容を固定した上で証拠量、実行時間、Python allocationのピーク、実効的なcontext境界を測るためのベンチマークである。生成モデル、生成条件、測定器、検査対象のカーネルsource、実行環境をreportのhash chainへ結び付ける。

このベンチマークはすべて合成した`authored_core`モデルを使う。T04原文packageやT05のtask/candidate/review/scope chainから作ったモデルではなく、自然文の解釈、法令との対応、法的な正しさは検査しない。得られる境界も、この固定workloadと現在の証拠形式についての値であり、一般的な規則数や法令規模の上限ではない。

## 固定したworkload

設定は[`config.json`](config.json)、決定的生成器は[`generate.py`](generate.py)、保存済みモデルとそのhashは[`generated/manifest.json`](generated/manifest.json)にある。乱数は使わない。

静的matrixは次の直積で8シナリオを作り、各シナリオについてbaseとrevisionを保存する。

| 軸 | 値 | 意味 |
|---|---|---|
| 規則数 | 50 / 100 | 10個のBool出力へ規則を循環配置 |
| guard | sparse / dense | 3個の独立Boolによる成立率1/8 / 7/8 |
| background | full / eighth | 全8,192状況を採用 / factsとconstraintsで1/8を採用 |

各matrixモデルは13個のBool入力を持つため、宣言Cartesian積は8,192状況である。`eighth`では`b10=true`のfactと`b11 and b12`のconstraintを使い、1,024状況を採用する。revisionは`R000.then.value`だけを`false`から`true`へ変え、その他のJSONはbaseと同一に保つ。

保存済みの4 sentinelは測定matrixとは別の意味回帰fixtureである。

- `sentinel-local-a.json`と`sentinel-local-b.json`: 個別には衝突しない領域。
- `sentinel-union-conflict.json`: 二領域を合わせたときだけ生じる衝突。
- `sentinel-override-revival.json`: 例外への例外で原則が復活する三段のoverride。

境界探索用familyは、1個の整数入力`case_id`、100個の常時成立規則、10個のBool出力、backgroundなし、overrideなしで固定する。context数だけを1から10,000まで変える。静的matrixの密度比較と、context数だけを増やす境界探索を混同しない。

## 測定方法

[`measure.py`](measure.py)は次の4経路を別々に測る。

| report内のoperation | カーネル経路 |
|---|---|
| `check` | `check` / 独立`verify` |
| `diff` | `diff` / 独立`verify-diff` |
| `reachability` | 旧`reachability` / 独立`verify-reachability` |
| `staged` | `reachability-staged` / 独立`verify-reachability-staged` |

既定の正式手順は、8静的シナリオ×4経路と、4経路それぞれの境界探索を実行する。producerとcheckerの時間は各3回、毎回fresh subprocessで測り、raw値とmin/median/maxを残す。producer timerはモデルloadと事後checkerを含まず、checker timerはモデル・certificate loadを含まない。各timing sampleの証拠はtimer外で独立checkerへ渡し、`VERIFIED`と同じcertificate hashを確認できた場合だけ成功として数える。

メモリ測定もproducerとcheckerを別々のfresh subprocessで1回ずつ実行する。値は`tracemalloc`による、入力load後のbaselineを超えたPython allocationのincremental peakである。OSのRSS、子process全体の最大常駐量、ネイティブallocationを表さない。時間とメモリは別実行なので単純に一つの実行として合算しない。

証拠量はcanonical UTF-8 JSONの正確なbytesで記録し、8 MiBは8,388,608 bytesとして残量も計算する。10,000状況は列挙のハード上限であり、処理成功の保証ではない。証拠8 MiBが先に効けば、より小さいcontext数で`LIMIT_REACHED`になる。

境界探索は固定familyについて1と10,000を調べ、10,000で`LIMIT_REACHED`なら二分探索して、連続する最後の成功と最初の失敗を求める。成功endpointは独立checkerの`VERIFIED`が必要である。最初の失敗では実CLIも呼び、新しいcertificateが残らないことと、既存targetのbytesを置換しないことを確認する。timeout、process異常、checker拒否は`LIMIT_REACHED`へ読み替えない。10,000まで成功した場合、最初の失敗は未観測のまま記録する。

reportには次を保存する。

- config、generator、generated manifest、測定器、関係するkernel sourceのraw SHA-256。
- configとmanifestのcanonical SHA-256、各モデルのhash・bytes・入出力数・規則数。
- OS、Python、CPU、総メモリ、workerのlocale・timezone・hash seed。
- guard/background/effective密度と各経路のraw測定値。
- 境界のprobe順、最後の成功、最初の`LIMIT_REACHED`、保存endpoint、部分artifact検査。
- report body全体のSHA-256。

`characterization.elapsed_ns_not_a_kernel_benchmark`は密度集計にかかった補助時間であり、カーネル性能値には使わない。

## 保存済み生成物を確認する

WSL Ubuntuでrepository rootへ移動して実行する。

```bash
cd /path/to/rule-formalization-lab
python3 -m benchmarks.t06.generate --check
python3 -m unittest tests.test_t06_benchmark tests.test_t06_measurement tests.test_t06_report_checker -v
python3 -m benchmarks.t06.report_checker \
  benchmarks/t06/results/2026-09-15.json \
  --expected-report-sha256 6bda457de5e19dbcbd74bb7df50f528b1c4dd6ca1e1040a972af35c7d3af1068
```

`generate --check`は一時directoryへ全生成物を作り直し、保存済み20モデルとmanifestをbyte-for-byteで比較する。`MATCH`以外なら正式測定へ進まない。

保存report専用checkerは外部に控えたraw report hashを必須入力にし、body hash、現在のsource/config/manifest/generated model、scenarioと密度、worker summary、boundaryとendpoint、失敗時非保存の記録、report出力と入力pathの分離を独立に検査する。正式reportは`VERIFIED`、static 8、boundary 4、完了workflow 27、`LIMIT_REACHED` workflow 13となる。timingと`tracemalloc`の値は整合性と算術を検査するが再実測しない。静的certificate本体もreportへ保存していないため、測定時checkerの記録とhashを検査する範囲に留まる。

## 正式測定

2026-09-15の正式測定は、結果file名だけを明示して次の形で実行した。他の測定optionは既定値である。

```bash
cd /path/to/rule-formalization-lab
python3 -m benchmarks.t06.generate --check
python3 -m benchmarks.t06.measure run \
  --output benchmarks/t06/results/2026-09-15.json
```

既定の出力先は`benchmarks/t06/results/report.json`、境界endpointは`benchmarks/t06/results/boundary-endpoints/`である。正式runだけは日付付きreportを指定した。全matrixと境界探索をfresh subprocessで繰り返すため、短いunit testより大幅に時間がかかる。

保存結果は[`results/2026-09-15.json`](results/2026-09-15.json)、詳しい読取りと再検査は[T06検証記録](../../docs/verification-t06-2026-09-15.md)にある。

| 項目 | 正式結果 |
|---|---|
| report raw SHA-256 | `6bda457de5e19dbcbd74bb7df50f528b1c4dd6ca1e1040a972af35c7d3af1068` |
| report body SHA-256 | `4c9478c881ec9ac15988a195e3309ba61652361131c087fbdf741c90e53dd7fe` |
| 静的matrix | 23/32経路が`VERIFIED`、9/32が証拠8 MiBで`LIMIT_REACHED` |
| check境界 | 5,661成功 / 5,662 `LIMIT_REACHED` |
| diff境界 | 3,172成功 / 3,173 `LIMIT_REACHED` |
| reachability境界 | 5,646成功 / 5,647 `LIMIT_REACHED` |
| staged境界 | 3,704成功 / 3,705 `LIMIT_REACHED` |

4つの最初の失敗はすべてexit 2で、新規certificateを残さず、既存targetのbytesも変えなかった。境界値は100個の常時成立規則・10出力という固定familyだけの値である。

既存の異なるreportやendpointは暗黙に置換しない。同じ場所を意図的に更新する場合だけ`--overwrite`を指定する。正式結果を残したまま再実行する場合は、次のように新しい一時directoryを使う。

```bash
cd /path/to/rule-formalization-lab
export T06_REPRO_DIR="$(mktemp -d)"
python3 -m benchmarks.t06.generate --output "$T06_REPRO_DIR/generated"
python3 -m benchmarks.t06.generate --output "$T06_REPRO_DIR/generated" --check
python3 -m benchmarks.t06.measure run \
  --generated "$T06_REPRO_DIR/generated" \
  --output "$T06_REPRO_DIR/report.json" \
  --endpoints "$T06_REPRO_DIR/boundary-endpoints"
sha256sum "$T06_REPRO_DIR/report.json"
```

生成モデルと証拠の意味結果は決定的だが、取得時刻、実行時間、メモリ、worker wall timeを含むreport全体のhashが別実行でも同じになることは要求しない。比較するときは、source/model binding、scenario、certificate hash・bytes、境界endpointと環境差を先に確認する。

## 短い動作確認

測定器の一経路だけを確認する場合は、正式値と区別した一時出力を使う。

```bash
cd /path/to/rule-formalization-lab
python3 -m benchmarks.t06.measure run \
  --profile matrix-50-sparse-eighth \
  --operation check \
  --repetitions 1 \
  --skip-boundaries \
  --output /tmp/t06-smoke-report.json
```

`--profile`と`--operation`は繰り返し指定できる。`--repetitions`は1から9までの奇数だけを受け付け、正式手順は3回である。`--skip-static`、`--skip-boundaries`、timeout変更を使った結果は、既定の正式測定と同じ完了結果として扱わない。

## 解釈上の境界

- `synthetic_not_t05_derived`は、原文単位数が0と判明したという意味ではない。T04/T05由来ではないため`source_unit_count`を`null`としている。
- `VERIFIED`は、保存した有限モデルとそのcertificateを独立checkerが再構成できたことを表す。モデルが現実の規則を正しく表すことや、カーネルの機械証明を意味しない。
- 1/8・7/8のguard密度と1/8のbackground適合率は、この生成profileの固定値である。他の条件式、ID・値の長さ、出力数、override構造では証拠bytesと境界が変わる。
- 背景で7/8を除外しても、現在のカーネルは宣言Cartesian積を列挙する。background適合率の低さをcontext予算の削減として扱わない。
- 時間値は保存環境での観測であり、別CPU、Python版、負荷状態へそのまま一般化しない。
- sentinelは局所分割の安全性を一般に証明しない。固定した人工例で、領域をまたぐ衝突を見落とせることを示す回帰fixtureである。
- 現CLIはreportの`--output`がconfig、manifest、generated model、kernel source等の入力pathと同じでないことを強制しない。修正までは、入力と異なる新規pathだけを使い、入力pathと`--overwrite`を組み合わせない。
- 長時間runの開始時に生成物を検査する一方、source bindingは終盤のfile bytesから作る。実行中の変更をsnapshotや前後hashで排除していないため、保存hashの一致は実行中ずっと同じbytesだったことまでは証明しない。

正式な数値、reportとendpointのSHA-256、各経路の最後の成功・最初の失敗、T12へ送る性能課題は、[検証記録](../../docs/verification-t06-2026-09-15.md)にreportから転記した。途中結果や掲示板の推計値を今回の完了値へ混ぜない。
