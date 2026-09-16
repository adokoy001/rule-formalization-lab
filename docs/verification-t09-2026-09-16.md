# T09 有限手続・時間の検証記録

日付: 2026-09-16
対象: `finite-procedure-time/1` / `procedurekernel`
fixture: [`t09-application`](../examples/procedures/t09-application/README.md)

## 実装した範囲

- 架空の申請、受領、審査、決定、通知を5 slot、5規範、4背景遷移で表した。
- `(tick, phase)`、排他的`observation_end`、closed prefix、future候補とabsent branchを固定した。
- 包含期限、異なる起算event、部分禁止、strict/non-strict先後、時刻未確定を区別した。
- deadlineの1〜8個の`targets`をany-ofとして扱い、将来の限定packで代替手続を表せるようにした。
- completion feasibility、observed prefix assessment、certificate verificationを別fieldにした。
- producerと、producerをimportしないchecker、`generate`/`verify` CLI、atomic新規保存を実装した。

## 保存fixture

`source.txt`は実在制度ではない9項目の架空規約である。`model.json`は16 contextを持つ。

- 決定期限の直前、包含境界ちょうど、同tickの後phase。
- 申請起算の受領期限と、受領起算の審査・決定期限。
- 同じ座標を同時とするnon-strict順序と、strict順序の背景不能。
- 審査禁止期間内の候補と、禁止終了後に復活する遵守候補。
- 通知未記録で観測終了が期限前、期限一致、期限後。
- 起算event欠落と、発生は観測したが時刻`null`の起算event。
- 一つの背景不能、三つの規範不能を、十の遵守可能contextから分けた。

保存結果は次のとおり。

| 項目 | 値 |
|---|---:|
| context | 16 |
| `compliance_feasible` | 10 |
| `normatively_infeasible` | 3 |
| `background_trace_impossible` | 1 |
| `completion_unresolved` | 2 |
| observed `fulfilled` / `pending` / `violated` | 5 / 2 / 3 |
| observed `unresolved_anchor` / `unresolved_time` | 4 / 1 |
| observed `background_violated` | 1 |

保存anchor:

```text
source.txt       4acc5e7adecac51cade440c5beae5053952ea9c32835a2f75146acec859e929c
model.json       e614d11bad5a2cd4026c5dc15aac94c547f9233d0acbe32bff0022848218a67c
certificate.json 4d034bb60c7a038fde3747ef26202e6b14a7d560360da200a2efbd438a71bca7
```

## 実行した確認

```bash
python3 -m unittest -v \
  tests.test_procedure_kernel \
  tests.test_procedure_cli \
  tests.test_t09_procedure_example
```

31件が合格した。正例に加えて次を確認した。

- `observation_end < due`と`== due`は`pending`、`> due`は`violated_missing`。
- deadline any-ofのどちらのtargetでも満足でき、どちらもない期限後は違反になる。
- 同座標はstrict先後を満たさず、non-strict先後を満たす。phase差は先後を作る。
- 全履行期間を禁止した例は有限completion上`normatively_infeasible`だが、期限前のobserved prefixは`pending`となる。
- 期限比較、座標順序、観測終了比較をproducerだけで壊した証拠をcheckerが拒否する。
- branch欠落、branch複製、順序反転、集計、witness、model hash、model差替えを拒否する。JSONの`false`と`0`も同一視せず、自己hash付き改ざん証拠を拒否する。
- 8 slot、4,096 trace/context、100,000組、1 MiB model、8 MiB証拠、64 bit加算をfail closedにした。
- 既存出力、model自身への出力、公開競合、link失敗で既存bytesを変えず、部分fileを残さない。

既存機能を含む回帰も実行した。

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q procedurekernel \
  tests/test_procedure_kernel.py tests/test_procedure_cli.py \
  tests/test_t09_procedure_example.py
```

全358件とcompileallが合格した。

CLIで保存fixtureを再生成し、独立checkerから`VERIFIED`を得た。fixtureには意図した注意対象が
あるためexit 1であり、検証失敗を表すexit 2とは異なる。

## 残る範囲

fixtureは宣言した離散候補だけを完全列挙し、連続時間や候補外時刻を被覆しない。
規約文からmodelへの変換は手書きで、原文対応checkerには未接続である。暦日、休日、期間法、
評価語、反復event、権限・裁量、overrideは未実装である。実法令へ進む際は、条文source、
取得版、限定解釈、未解決依存を別に固定し、数値期限だけから手続全体の適法性を結論しない。
