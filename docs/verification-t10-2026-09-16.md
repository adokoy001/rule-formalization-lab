# T10 刑事訴訟法203条から205条の限定pack検証記録

日付: 2026-09-16
対象: [`t10-criminal-procedure-203-205`](../examples/procedures/t10-criminal-procedure-203-205/README.md)

## 完了した範囲

e-Govの2026-08-13施行revision `323AC0000000131_20260813_508AC0000000067`を固定し、55条・203条・204条・205条・206条をArticle単位の5 source unitとして保存した。203条で送致された経路に限定し、次の三つを別normとして診断する。

| norm | 起算 | any-of target | 包含上限 |
|---|---|---|---:|
| `A203_SEND_48H` | 身体拘束 | 送致手続 | 48 hour |
| `A205_RECEIPT_24H` | 検察官の受領 | 勾留請求又は公訴提起 | 24 hour |
| `A205_RESTRAINT_72H` | 身体拘束 | 勾留請求又は公訴提起 | 72 hour |

送致手続と受領は別slotである。`observation_end`は排他的で、期限座標と同じ終端まで行為が未観測なら`pending`、同じtickの後phaseまで進めば`violated_missing`になる。206条の事情説明と評価slotは数値normから分離し、事情説明だけで標準期限を延長しない。

## source・review・binding

source bundleの外部anchor付きoffline再検査は`VERIFIED`、source unit 5、未解決reference 5だった。coverageは55条`partial`、203条`partial`、204条`out_of_scope`、205条`partial`、206条`unresolved`である。

`task.json`、非信頼`candidate.json`、`review.json`、`model.json`、`certificate.json`、全文quoteを含む5 source unitを`binding.json`へ結合した。reviewは`manual_fixture_review`、`provisional: true`である。独立checkerの結果名は`MANUAL_MODEL_BINDING_VERIFIED`で、`semantic_lowering_proved: false`、`legal_conclusion: false`を返す。

| artifact | SHA-256 |
|---|---|
| source bundle | `6c8510b9c9022c6d4974bd1cc00fffdcd85b1ca4547f1027c644b68c5dc9a7fe` |
| source unit manifest | `74f57298be484950f31b89dacfb81908f637b02ab2eb8b8d14e43a618bf1a7a8` |
| task | `7e632ccc46de8a2b14f73c567e6381657d4823f88d0392df13274f9d293f3f98` |
| candidate | `abdc9adba9169e774be3906dc3196b824b0e1a2192c9c584e7dbb60c12b0ca94` |
| review | `421b90a5a58f544aa842b1c1e2a9c1f4bd17eb202bb9f9ad91ccbae0840882cb` |
| model | `e255570d7ff365b4c79afbbcdf2a65bb7e036ee9b10fa507216579560a192f6f` |
| certificate | `a4e62ff42528c1abe55d4635f7ec3a85019a6fa39b45a47715cf824e647d62b3` |
| binding | `e76cf9be471e45a5f83cb35083c15470f8f4ff3be6c1424ad3e97aec3b126811` |

## 13 contextの結果

- 203条は送致が48時間ちょうどなら`satisfied`、49時間なら`violated_late`。未記録で観測終了が期限と同じなら`pending`、後phaseなら`violated_missing`。
- 205条は全期限境界内、公訴提起による代替、受領後24時間だけ超過、拘束後72時間だけ超過をそれぞれ固定した。
- 行為なしで観測終了が72時間と同じ場合は両205 normが`pending`、後phaseでは両方`violated_missing`。
- 206条事情説明を持つ73時間の勾留請求は、受領後24時間には`satisfied`、拘束後72時間には`violated_late`のままである。
- pack診断は203条の48時間違反、又は205条の二期限の一方以上の違反を、期限後行為と期限後までの欠落の双方から`SELECTED_TEXT_RELEASE_TRIGGERED`として再構成し、実際の`RELEASE_OBSERVED`と分離する。206条は`ARTICLE_206_ASSESSMENT_UNRESOLVED`を出す。

certificate集計はcontext 13、observed `fulfilled` 3、`pending` 1、`violated` 7、`unresolved_anchor` 2。completionは`compliance_feasible` 3、`normatively_infeasible` 10だった。A203だけを見るcontextでA205の受領anchorがまだない状態も保持するため、全体outcomeと個別norm statusを混同しない。

## 検証

```bash
python3 -m unittest -v tests.test_t10_criminal_procedure tests.test_t10_binding
python3 -m unittest discover -s tests -q
python3 -m compileall -q rulekernel normkernel procedurekernel tests benchmarks
```

T10専用25件、全suite 358件、`compileall`が合格した。外部anchor付きprocedure certificateは`VERIFIED`だが注意対象を含むためexit 1、binding checkerは`MANUAL_MODEL_BINDING_VERIFIED`でexit 0だった。T06 report checker、T08、T09、T10 source bundleの固定anchorも回帰した。

負例は、全文quote・unit ID・text hash、candidate、review、coverage、model、certificate、binding、source bundle、law IDの改ざんを拒否する。acceptance norm集合の重複・欠落、nested型不正、JSONのBoolean・整数・小数の型置換、source検証直後のspec又はmanifest差替えもfail closedで拒否する。source checkerもbundle lockをcanonical bytesで比較し、外部anchorなしの整数から小数への型置換を拒否する。受領起点を送致起点へ変える、205条の二期限の片方を削る、206条を自動延長に変える自己整合寄り変異も拒否した。binding checkerはbinding producerをimportしない。

## 保証しない範囲

このpackは有限な標準数値期限診断であり、原文からmodelへの意味的lowering、法律専門家の承認、手続全体の適法・違法、個別事実の認定を保証しない。204条経路、55条の一般暦、56条・規則66条等の延長、206条の事情・疎明・裁判官判断、207条以降は未解決又は対象外である。将来revision `323AC0000000131_20270331_507AC0000000039`が施行されたらstaleとして再作成する。
