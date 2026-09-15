# T06 合成ベンチマーク検証記録

実施日: 2026-09-15

## 結論

T06の固定合成ベンチマークについて、決定的生成物、8静的scenario×4検査経路、1〜10,000 contextの固定境界family、独立checker、証拠上限時の非保存を一つのreportへ保存した。

静的32測定のうち23件はproducerと独立checkerが同じcertificate hashで`VERIFIED`となり、9件はproducerが証拠8 MiB上限で`LIMIT_REACHED`になった。境界familyでは4経路すべてで10,000より前に証拠上限へ達し、最後の成功と最初の失敗が連続することを確認した。これにより、現形式では探索contextのハード上限より証拠容量が先に制約になる固定例を再現できた。

これは[`benchmarks/t06`](../benchmarks/t06/README.md)の合成`authored_core` workloadについての完了である。T04原文packageやT05 task/candidate/review/scope chainに由来せず、自然文の解釈、法的正しさ、他のモデルに共通する性能上限を証明しない。

## 正式reportと完全性

正式reportは[`benchmarks/t06/results/2026-09-15.json`](../benchmarks/t06/results/2026-09-15.json)である。

| 項目 | 値 |
|---|---|
| format | `t06-benchmark-report/1` |
| measurement version | `0.1.0` |
| raw file bytes | 238,086 |
| raw file SHA-256 | `6bda457de5e19dbcbd74bb7df50f528b1c4dd6ca1e1040a972af35c7d3af1068` |
| 保存body SHA-256 | `4c9478c881ec9ac15988a195e3309ba61652361131c087fbdf741c90e53dd7fe` |
| 再計算body SHA-256 | `4c9478c881ec9ac15988a195e3309ba61652361131c087fbdf741c90e53dd7fe` |
| 静的scenario | 8 |
| 静的測定 | 23 `VERIFIED` / 9 `LIMIT_REACHED` |
| 境界経路 | 4、すべて連続境界を発見 |
| 正式反復 | 3、reportでも`standard_three_repetition_run=true` |

body hashは`rulekernel.model.digest(report["body"])`で再計算した。reportが列挙する16個のbinding fileも現在のraw bytesからSHA-256とsizeを再計算し、全件一致した。

保存report専用の[`report_checker.py`](../benchmarks/t06/report_checker.py)も、外部raw file hashを指定して実行した。

```bash
python3 -m benchmarks.t06.report_checker \
  benchmarks/t06/results/2026-09-15.json \
  --expected-report-sha256 6bda457de5e19dbcbd74bb7df50f528b1c4dd6ca1e1040a972af35c7d3af1068
```

結果は`VERIFIED`、body SHA-256一致、static 8、boundary 4、完了workflow 27、`LIMIT_REACHED` workflow 13だった。checker fileのraw SHA-256は`f9e5e869c1cdae5e4cc5b71a030ceed3cf723affb73189b60c314506dc2c2946`。このcheckerはproducerをimportせず、外部anchor、現在のsource/config/manifest/generated model、reportの構造と算術、密度、raw 3 sampleのstatus、boundary endpoint、report出力と入力pathの分離を検査する。

checkerはtimingと`tracemalloc`を再実測せず、環境値の第三者attestationでもない。静的matrixのcertificate本体はreportへ保存していないため、測定時のchecker statusとcertificate hash・summaryの整合性を検査する。境界成功certificateは下記の独立replayで補った。

## 固定した入力とhash

| binding | bytes | raw SHA-256 |
|---|---:|---|
| `benchmarks/t06/config.json` | 512 | `0b40490e80527caee2f172a3fe67948dcf05e52b1c140c4e1d9236f2fb3c79a7` |
| `benchmarks/t06/generate.py` | 11,950 | `5e5d953e3dcbf7942e2a09991a038032bbca9334385190cf327c5fb7db10e191` |
| `benchmarks/t06/generated/manifest.json` | 7,683 | `880d4c3bdb2894380096526d091ad4396510b4631d9ed9f93fbb164d11192877` |
| `benchmarks/t06/measure.py` | 56,931 | `1f0153c78ff9467542a76e22533df7409d23219429e0c526916d5f7c371eec09` |
| `rulekernel/__main__.py` | 27,862 | `d88b254a315b1997011df3cbf517a7d234944427de844ed6f9b6252473578d5a` |
| `rulekernel/model.py` | 11,574 | `d25133ef6c8a72f3d40ff1318adf57290b9c71b6e83e3b48637834ce603ba332` |
| `rulekernel/engine.py` | 5,217 | `65799c547a3c30c7cdc736fd61eccbe8adf2816c6dfc60b515af95141defe99a` |
| `rulekernel/checker.py` | 9,917 | `db5c15ff0468031d980e53a28fc5af0d2587ee12cdebc51835ade14a83e9b043` |
| `rulekernel/diff.py` | 7,964 | `f6e637077c445eefd65cc481dd453ba3921e0a61ee35e71d9c85f1c86b418614` |
| `rulekernel/diff_checker.py` | 12,537 | `b6f8c3330d2a90228b89bc64532b9447b91d351fc44aab52ac591ec6f5e3be3a` |
| `rulekernel/reachability.py` | 5,740 | `5339a5c8346cb0cc475aecfc6ff8aab7bcd3130635afc83fb9fce9cf73e68127` |
| `rulekernel/reachability_checker.py` | 9,927 | `a3e14e4314566b7b3ad37f3a5d2c025870704c50965c3723f5c96ecf52189124` |
| `rulekernel/staged_reachability.py` | 14,869 | `e21e081e7cd132593090f03ccdbac614f0e225a80450eed2ffd5f96270a6e016` |
| `rulekernel/staged_reachability_checker.py` | 19,501 | `5af332bdbcdcfff6051016b96009651b980c65ae8704693ed26ccb1c7c4ef156` |
| `rulekernel/staged_reachability_model.py` | 6,772 | `46e3e62cfe24de489de0dc36d04497f40f9e2ffaf0c2abd41307a7df5306a6e5` |
| `rulekernel/interpretation_model.py` | 36,572 | `200c4402f4a6eb27d330b7a9c943be1c72e7f75e527adc42cca41533989eae4f` |

configのcanonical SHA-256は`ca0789c343fbabe5270deee399440cfe7ee28475cb37f09da1bdcd1317e30f6d`。manifestは保存fileとcanonical表現が同じbytesで、いずれも`880d4c3bdb2894380096526d091ad4396510b4631d9ed9f93fbb164d11192877`だった。manifestの20 entryと保存済み生成物は決定的再生成で一致する。

## 実行環境と測定契約

| 項目 | 値 |
|---|---|
| captured at UTC | `2026-09-15T14:54:33.858583+00:00` |
| OS | Linux `6.18.33.2-microsoft-standard-WSL2`、x86_64 |
| CPU | Intel(R) Core(TM) i5-10310U CPU @ 1.70GHz |
| `/proc/meminfo` MemTotal | 7,988,856 kB |
| Python | CPython 3.14.4、`/usr/bin/python3` |
| worker環境 | `PYTHONHASHSEED=0`、`TZ=UTC`、`LC_ALL=C.UTF-8` |
| certificate上限 | 8,388,608 bytes = 8 MiB |
| context上限 | 10,000 |
| subprocess timeout | 180.0秒 |

producerとcheckerは各3回をfresh subprocessで測った。下表の時間はraw 3回のmedianをnanosecondで示す。producer timerはmodel loadと事後checkerを含まず、checker timerはmodel/certificate loadを含まない。メモリは別processの`tracemalloc`で、load済み入力をbaselineとしたincremental Python allocation peakのbytesであり、RSSではない。成功はoperation固有の独立checkerが同じcertificate hashを`VERIFIED`とした場合に限る。

実行コマンドの引数は、全8 profile、全4 operation、反復3、static/boundaryとも省略なし、固定生成物の再生成なしだった。

```bash
python3 -m benchmarks.t06.measure run \
  --output benchmarks/t06/results/2026-09-15.json
```

## workload密度

全scenarioは13 Bool、8,192宣言context、10出力を持つ。guard分母は`context数 × 規則数`である。

| scenario | 規則 | 採用context | guard成立 | enabled |
|---|---:|---:|---:|---:|
| `50-sparse-full` | 50 | 8,192 | 51,200 / 409,600 = 1/8 | 51,200 / 409,600 = 1/8 |
| `50-sparse-eighth` | 50 | 1,024 | 51,200 / 409,600 = 1/8 | 6,400 / 409,600 = 1/64 |
| `50-dense-full` | 50 | 8,192 | 358,400 / 409,600 = 7/8 | 358,400 / 409,600 = 7/8 |
| `50-dense-eighth` | 50 | 1,024 | 358,400 / 409,600 = 7/8 | 44,800 / 409,600 = 7/64 |
| `100-sparse-full` | 100 | 8,192 | 102,400 / 819,200 = 1/8 | 102,400 / 819,200 = 1/8 |
| `100-sparse-eighth` | 100 | 1,024 | 102,400 / 819,200 = 1/8 | 12,800 / 819,200 = 1/64 |
| `100-dense-full` | 100 | 8,192 | 716,800 / 819,200 = 7/8 | 716,800 / 819,200 = 7/8 |
| `100-dense-eighth` | 100 | 1,024 | 716,800 / 819,200 = 7/8 | 89,600 / 819,200 = 7/64 |

override辺がないため、このmatrixではeffective密度はenabled密度と同じである。backgroundが1/8でも現在の実装は全8,192宣言contextを列挙する。

## 静的matrixの結果

`VERIFIED`行だけに完全なcertificate、独立checker時間、checker memoryがある。`LIMIT_REACHED`行はすべてproducer prepareで証拠上限に達したため、失敗時の経過時間や途中構造を成功測定へ混ぜず空欄にした。

| scenario | operation | status | certificate bytes | 8 MiB残量 | producer median ns | checker median ns | producer peak bytes | checker peak bytes |
|---|---|---|---:|---:|---:|---:|---:|---:|
| `50-sparse-full` | check | VERIFIED | 2,496,234 | 5,892,374 | 712,775,386 | 1,081,156,061 | 12,683,543 | 15,302,546 |
| `50-sparse-full` | diff | LIMIT_REACHED | — | — | — | — | — | — |
| `50-sparse-full` | reachability | VERIFIED | 2,521,552 | 5,867,056 | 583,675,966 | 1,563,309,547 | 12,821,891 | 15,468,420 |
| `50-sparse-full` | staged | VERIFIED | 3,396,938 | 4,991,670 | 657,563,726 | 2,008,636,698 | 16,350,183 | 19,891,706 |
| `50-sparse-eighth` | check | VERIFIED | 1,885,176 | 6,503,432 | 216,344,999 | 387,502,248 | 10,474,599 | 12,482,424 |
| `50-sparse-eighth` | diff | VERIFIED | 3,223,514 | 5,165,094 | 514,409,172 | 1,052,746,235 | 24,423,164 | 26,210,247 |
| `50-sparse-eighth` | reachability | VERIFIED | 1,910,094 | 6,478,514 | 172,276,838 | 728,876,620 | 10,608,947 | 12,643,898 |
| `50-sparse-eighth` | staged | VERIFIED | 2,822,255 | 5,566,353 | 646,870,763 | 2,993,326,239 | 14,418,421 | 17,385,211 |
| `50-dense-full` | check | VERIFIED | 6,790,922 | 1,597,686 | 2,243,317,212 | 2,559,321,344 | 26,352,221 | 33,263,896 |
| `50-dense-full` | diff | LIMIT_REACHED | — | — | — | — | — | — |
| `50-dense-full` | reachability | VERIFIED | 6,816,150 | 1,572,458 | 947,062,911 | 2,101,988,307 | 26,490,159 | 33,429,206 |
| `50-dense-full` | staged | LIMIT_REACHED | — | — | — | — | — | — |
| `50-dense-eighth` | check | VERIFIED | 2,422,012 | 5,966,596 | 409,222,715 | 535,276,517 | 12,185,205 | 14,727,850 |
| `50-dense-eighth` | diff | VERIFIED | 3,844,824 | 4,543,784 | 767,272,229 | 1,668,425,934 | 27,157,296 | 29,304,001 |
| `50-dense-eighth` | reachability | VERIFIED | 2,446,840 | 5,941,768 | 206,763,839 | 493,412,217 | 12,322,343 | 14,891,960 |
| `50-dense-eighth` | staged | VERIFIED | 5,506,230 | 2,882,378 | 826,921,827 | 2,537,519,660 | 22,959,427 | 28,608,194 |
| `100-sparse-full` | check | VERIFIED | 3,213,034 | 5,175,574 | 1,697,323,900 | 2,136,895,447 | 14,998,007 | 18,328,762 |
| `100-sparse-full` | diff | LIMIT_REACHED | — | — | — | — | — | — |
| `100-sparse-full` | reachability | VERIFIED | 3,264,243 | 5,124,365 | 1,071,919,113 | 3,036,234,263 | 15,275,529 | 18,668,189 |
| `100-sparse-full` | staged | VERIFIED | 4,569,459 | 3,819,149 | 1,224,845,718 | 3,017,156,380 | 20,204,921 | 24,921,157 |
| `100-sparse-eighth` | check | VERIFIED | 1,974,776 | 6,413,832 | 390,914,088 | 463,374,293 | 10,771,271 | 12,863,648 |
| `100-sparse-eighth` | diff | VERIFIED | 3,313,254 | 5,075,354 | 669,100,644 | 1,270,373,796 | 23,725,468 | 26,571,371 |
| `100-sparse-eighth` | reachability | VERIFIED | 2,025,185 | 6,363,423 | 258,136,846 | 611,166,423 | 11,040,793 | 13,194,275 |
| `100-sparse-eighth` | staged | VERIFIED | 3,393,711 | 4,994,897 | 959,373,311 | 3,186,929,045 | 16,449,573 | 19,990,061 |
| `100-dense-full` | check | LIMIT_REACHED | — | — | — | — | — | — |
| `100-dense-full` | diff | LIMIT_REACHED | — | — | — | — | — | — |
| `100-dense-full` | reachability | LIMIT_REACHED | — | — | — | — | — | — |
| `100-dense-full` | staged | LIMIT_REACHED | — | — | — | — | — | — |
| `100-dense-eighth` | check | VERIFIED | 3,049,212 | 5,339,396 | 573,581,942 | 810,509,552 | 14,214,997 | 17,373,650 |
| `100-dense-eighth` | diff | VERIFIED | 4,472,164 | 3,916,444 | 1,239,365,252 | 1,831,233,255 | 29,400,560 | 31,769,445 |
| `100-dense-eighth` | reachability | VERIFIED | 3,099,441 | 5,289,167 | 304,861,907 | 713,319,686 | 14,490,265 | 17,709,779 |
| `100-dense-eighth` | staged | LIMIT_REACHED | — | — | — | — | — | — |

9件の失敗はtimeoutやchecker拒否ではない。check 1件、diff 4件、reachability 1件、staged 3件が、それぞれの完全なcanonical certificateを8 MiB以内に生成できず`LIMIT_REACHED`になった。特に`100-dense-full`は4経路すべて上限に達した一方、同じ13 Bool・100規則でもbackgroundを1/8にするとcheck/diff/reachabilityは完了した。規則数とcontext数だけでなく、guard成立密度、background適合率、証拠形式が実効容量を左右する。

## 連続する実効境界

境界familyは1個の整数入力、100個の常時成立規則、10 Bool出力、全context採用、overrideなしで、context数だけを変える。下表の時間とメモリは最後の成功endpointの値である。

| operation | 最後の成功 | 最初のLIMIT_REACHED | 成功証拠bytes | 残量 | 証拠SHA-256 | producer median ns | checker median ns | producer peak bytes | checker peak bytes |
|---|---:|---:|---:|---:|---|---:|---:|---:|---:|
| check | 5,661 | 5,662 | 8,388,230 | 378 | `4da7e618d500e3427d6b7cc81da92227b27801074dec92675a848137ac0b3947` | 2,383,951,065 | 2,982,867,240 | 29,701,193 | 38,198,732 |
| diff | 3,172 | 3,173 | 8,388,422 | 186 | `a62b0dcb1439e93bef96a0cae8ec194693dca4eb32c17382ec155120a8503b25` | 3,231,335,886 | 3,044,445,466 | 54,403,192 | 55,485,355 |
| reachability | 5,646 | 5,647 | 8,388,229 | 379 | `617eb14782dbd478c26a2f169ab596e2ec5628a6fbd1a868142fe239d756e3bf` | 853,455,261 | 1,262,042,532 | 29,785,721 | 38,294,707 |
| staged | 3,704 | 3,705 | 8,388,025 | 583 | `fb4b46a126aa47117ac0b70e747f098dd727f9d96985ace4d34360a485e727e1` | 831,952,574 | 1,222,421,648 | 29,147,161 | 37,673,815 |

保存したendpointのraw SHA-256もreport値と現物で一致した。

| endpoint | bytes | raw SHA-256 |
|---|---:|---|
| `check-last-success-05661.json` | 15,190 | `07c7b2e0adc427649bd0b7e13e45249208972db8e3355dbc653343ac318dd03b` |
| `check-first-failure-05662.json` | 15,190 | `6ca9d02535fb589adaf6588e4f11103dc0e63590c6d5731418d7771cd79f8a6a` |
| `diff-last-success-03172.json` | 15,190 | `7834be665f6ff9e014877dcaddce0ab612f83dbb307bfd59ff9bc76b643afe75` |
| `diff-last-success-03172-revision.json` | 15,189 | `2cbdce71e65f30814b5e2885b07be3dcf2beba1d1aae0cb7f241613878a4104f` |
| `diff-first-failure-03173.json` | 15,190 | `08db3f68c4f8d098555d49812713715fa3757b7fd46482ff90add1dc4a60bc15` |
| `diff-first-failure-03173-revision.json` | 15,189 | `9ffb2d8eaa807d60d67ddbea21b830f2de36590d92be2a75651fcae777a6a886` |
| `reachability-last-success-05646.json` | 15,190 | `7f97701407f93dede6cf4c57b60bd69a508bdcb7329a08d7a41b5cc81187b2af` |
| `reachability-first-failure-05647.json` | 15,190 | `8ceaadd871ab8174ef5e5ac16f6c3ea275d365b4d11a188c5bf1773e5b55872b` |
| `staged-last-success-03704.json` | 15,190 | `c1a7873b1258a34feff1832a28526c8c477557548ece0590011965dbfdc60eef` |
| `staged-first-failure-03705.json` | 15,190 | `7b9938fb4b40d726f6078fe7dfade07f7a024a550941eb30b6e6ceffbeed7508` |

4つの最初の失敗について実CLIを一時targetへ2回ずつ実行した。targetが存在しない場合は新しいcertificateを残さず、sentinelが存在する場合はそのbytesを変更せず、いずれもexit 2とJSON `LIMIT_REACHED`を返した。4経路とも`partial_artifact_check.passed=true`で、既存sentinelの前後SHA-256は`b0e2300bae0784de01be8bd49d229fe58037f0fa66f38c3d948b7766912552a8`だった。

## 2026-09-16の独立replay

正式reportを読む監査とは別に、保存した最後の成功endpointから`/tmp`へ4 certificateを再生成し、operation固有のcheckerへ渡した。bytesとSHA-256は上の境界表と全件一致し、checkerはすべて`VERIFIED`だった。

最初の一時replay scriptは、全producer/checkerがexit 0になると誤って仮定し、意味差を正しく見つけた`diff`のexit 1で停止した。statusと終了コードを分離するよう訂正して再実行した。`diff`はproducer/checkerともexit 1でありながらcertificateは`VERIFIED`で、これは差分を注意対象とするCLI仕様どおりである。他の成功経路はexit 0だった。

4つの最初の失敗endpointも各2回CLI replayし、全件でexit 2、JSON `LIMIT_REACHED`、新規targetなし、既存sentinel bytes不変を再確認した。report構造の独立assertはstatic scenario 8、operation 32、期待した上限到達9、boundary 4、endpoint 10で合格した。

回帰確認:

```text
python3 -m benchmarks.t06.generate --check
MATCH

python3 -m unittest tests.test_t06_benchmark tests.test_t06_measurement tests.test_t06_report_checker -q
Ran 22 tests in 18.058s
OK

python3 -m unittest discover -s tests -q
Ran 253 tests in 23.574s
OK

python3 -m compileall -q rulekernel tests benchmarks
exit 0
```

## 既知の制約

### 合成データの境界

全モデルは`synthetic_not_t05_derived`で、manifestの`source_unit_count`は0ではなく`null`である。T04原文、T05 task/candidate/review/scope、専門家reviewを持たない。したがって、この結果から原文の正しい形式化、法的解釈、刑法・刑事訴訟法の整合性を主張しない。固定familyの境界は、規則数一般、別のID・値長、override、別出力数、別証拠形式へ一般化しない。

### report出力と入力pathの分離を強制していない

レビューで、`measure run --output`がconfig、manifest、generated model、kernel source等の入力pathと同一でないことを明示検査していないと分かった。通常の既定出力は入力と分離されており、今回の正式runも`benchmarks/t06/results/2026-09-15.json`を使ったため該当しない。ただし、利用者が同じpathを明示し、`--overwrite`も使うと、測定後に入力をreportで置換し得る。修正までは、既存入力と別の新規report/endpoints pathだけを指定する。

### 長時間run中のbinding raceを排除していない

測定開始時に固定生成物を検査する一方、source bindingは長い測定の終盤に現在のfile bytesから作る。測定中にconfig、generator、manifest、generated model、kernel sourceが変更された場合、各workerが実際に読んだ版と最終bindingが一致しないraceをreport単体では排除できない。今回、完了後の16 bindingと10 endpointは現物へ一致したが、「実行中ずっと不変だった」ことの暗号学的証明ではない。将来は入力snapshot上で全workerを走らせるか、開始前後hash一致を必須にして不一致ならreportを公開しない。

### 測定器と性能値の限界

測定器とchecker自体の機械証明はない。`tracemalloc`はRSSではなく、timingとmemoryは別processの別実行である。OS負荷や別環境で時間値は変わる。`LIMIT_REACHED`は現在の完全証拠表現と固定8 MiB上限による確定不能であり、対象規則に問題がないことも、探索不能であることも意味しない。

## 判断と次の一歩

T06は、証拠bytesが現行全数証拠の最初の容量制約になり得ることを再現可能に示した。T12では、全範囲の被覆、欠落・重複・途中切断・偽集計の拒否と独立再構成を保つ省サイズ表現を優先候補にする。`tracemalloc` peakと実行時間も保存したが、このreportだけを根拠にSAT化を先行させない。

次はT07で、保存済み刑法41条snapshotから小さな手書きpackを作る。T07は限定論点・小scopeを維持し、T12を完了前提にしない。証拠上限へ近づく拡張を始める前にT12を実施する。

## 再検査コマンド

```bash
cd /path/to/rule-formalization-lab
python3 -m benchmarks.t06.generate --check
python3 -m unittest \
  tests.test_t06_benchmark \
  tests.test_t06_measurement \
  tests.test_t06_report_checker -v
python3 -m benchmarks.t06.report_checker \
  benchmarks/t06/results/2026-09-15.json \
  --expected-report-sha256 6bda457de5e19dbcbd74bb7df50f528b1c4dd6ca1e1040a972af35c7d3af1068
python3 - <<'PY'
from pathlib import Path
import hashlib, json
from rulekernel.model import digest

path = Path("benchmarks/t06/results/2026-09-15.json")
raw = path.read_bytes()
report = json.loads(raw)
assert hashlib.sha256(raw).hexdigest() == "6bda457de5e19dbcbd74bb7df50f528b1c4dd6ca1e1040a972af35c7d3af1068"
assert digest(report["body"]) == report["body_sha256"] == "4c9478c881ec9ac15988a195e3309ba61652361131c087fbdf741c90e53dd7fe"
print("REPORT_VERIFIED")
PY
```

文書close後、Markdown 38 filesの相対link 332件を解決し、missing 0、UTF-8 decode error 0、CRLF file 0を確認した。JSON 77 filesもstrict UTF-8 decodeとparseが全件成功した。
