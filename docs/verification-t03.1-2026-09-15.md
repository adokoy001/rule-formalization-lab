# T03.1 段階別到達可能性検証記録

実施日: 2026-09-15。対象: [段階別到達可能性診断 v0.1](staged-reachability-v0.1.md)。
これは`finite-decisions/1`の固定有限domainについて、guard、facts、constraints、overrideの
各段階を全列挙して再検査した記録である。原文の法的な正しさや、host scope期待の妥当性を
証明した記録ではない。

## 実装した経路

- T05 scope expectationsをCoreへ結ぶconsumer: [`staged_reachability_model.py`](../rulekernel/staged_reachability_model.py)
- 全contextと段階行を作るproducer: [`staged_reachability.py`](../rulekernel/staged_reachability.py)
- producerと旧reachabilityをimportせず全証拠を再構成するchecker: [`staged_reachability_checker.py`](../rulekernel/staged_reachability_checker.py)
- `reachability-staged`、`verify-reachability-staged`: [`__main__.py`](../rulekernel/__main__.py)

旧`reachability`の形式、分類、CLI、終了コードは変更していない。新形式は
`finite-decisions-staged-reachability-certificate/1`である。

## 星見クラブ資料形式fixture

T03.1用に、Club20 fixedの第19条・第20条と同じ架空原文をT04/T05の小さい入力束へした。

- [固定原文package](../examples/sources/handbook-scope/README.md)
- [手書き解釈、host review、scope expectations](../examples/interpretations/handbook-scope/README.md)

T03.1を実行する前に、保存済みT05 packageをsource bundle、review、scope expectations、
compiled packageの外部hash付きで`verify-interpretation`へ渡した。結果はexit 0、
`LOWERING_VERIFIED`、`offline=true`で、全外部anchorがtrueだった。T03.1自身はこの
source/review chainを再構成しないため、この検査を別に行った。

段階別検査の固定値と実測は次のとおり。

| 項目 | 値 |
|---|---|
| Core model SHA-256 | `3baed24f29c0822257db9e12920fbc75be2852b99d99e8f588b1d1bcb84554d6` |
| scope expectations canonical JSON SHA-256 | `a9f95803953cdf36a641dc3cf8023b0833b3b94b450da44572f71ff7fcd12b5d` |
| source-unit manifest SHA-256 | `1170350e93942928d90c68101169a7560b0f280997018e542963cbc614081c11` |
| [保存したstaged certificate](../examples/interpretations/handbook-scope/staged-reachability.certificate.json) SHA-256 | `d6e9bf6758ad5277b70accb54647a77b5e3f6f06969974438b4a9a2761082453` |
| 全Cartesian積 / facts適合 / constraints適合 / 両方適合 | 52 / 52 / 52 / 52 |
| attention | 0 |

| Core rule | guard | guard+facts | guard+constraints | enabled | effective | Host期待 / 結果 |
|---|---:|---:|---:|---:|---:|---|
| `IR_P_HANDBOOK_PAPER` | 26 | 26 | 26 | 26 | 26 | `expected_in_scope` / `matched_in_scope` |
| `IR_P_HANDBOOK_AGE_EXCEPTION` | 0 | 0 | 0 | 0 | 0 | `expected_inactive` / `matched_inactive` |

第20条の`age >= 26`には、age 0〜25との
`atomic_integer_comparison_disjoint_from_declared_domain` hintが付いた。
期待入力を外すと同じ有限件数でも第20条は`INACTIVE_WITHOUT_EXPECTATION`となり、exit 1。
age上限を26へ変えたCoreへ古い期待を渡すと`EXPECTATIONS_MISMATCH`、exit 2になる。
Core/scope hashを新しい値へ結び直しても期待を`expected_inactive`のままにすると、
第20条はguard/enabled 2、最初のwitnessはcase 52の`age=26, student=false`となり、
`EXPECTED_INACTIVE_BUT_REACHED`、exit 1になる。

実行例:

```bash
python3 -m rulekernel reachability-staged \
  examples/interpretations/handbook-scope/core.json \
  --scope-expectations examples/interpretations/handbook-scope/scope-expectations.json \
  --expected-scope-expectations-sha256 a9f95803953cdf36a641dc3cf8023b0833b3b94b450da44572f71ff7fcd12b5d \
  --certificate /tmp/handbook-scope.staged.json --json

python3 -m rulekernel verify-reachability-staged \
  examples/interpretations/handbook-scope/core.json \
  examples/interpretations/handbook-scope/staged-reachability.certificate.json \
  --scope-expectations examples/interpretations/handbook-scope/scope-expectations.json \
  --expected-scope-expectations-sha256 a9f95803953cdf36a641dc3cf8023b0833b3b94b450da44572f71ff7fcd12b5d \
  --json
```

保存証拠の再検査はexit 0、`VERIFIED`、attention 0で、上記certificate hashと一致した。

## 既存T05会員規約との接続

[架空会員規約](../examples/interpretations/member-eligibility/README.md)の保存済みCoreと
外部hash付きscope expectationsもそのまま入力した。

| 項目 | 実測 |
|---|---|
| 全Cartesian積 / facts適合 / constraints適合 / 両方適合 | 104 / 104 / 78 / 78 |
| `IR_P_ADULT_MEMBER` | guard 16 / guard+facts 16 / guard+constraints 16 / enabled 16 / effective 8 |
| `IR_P_SUSPENSION_EXCEPTION` | guard 52 / guard+facts 52 / guard+constraints 26 / enabled 26 / effective 26 |
| scope期待 | 2規則とも`matched_in_scope` |
| attention | 0 |
| [保存証拠](../examples/interpretations/member-eligibility/staged-reachability.certificate.json) SHA-256 | `89aee1333f46ddfccf0bfdeac09565297a00b2cd96a9b0fcdf323a0b4ff3202b` |

成人規則は利用停止例外により一部抑止されるため`partially_suppressed`、例外は
`always_effective_when_enabled`となった。`expected_in_scope`はenabledとの一致を表し、
一部抑止を隠さない。

## 固定した段階差と負例

専用回帰では次を固定した。

- `flag and not flag`とage 0〜25の`age >= 26`はいずれもguard 0。後者だけに安全な原子比較hintを付け、`age >= 25`には誤hintを付けない。
- guard成立例をfactsだけが全て除外する例、constraintsだけが全て除外する例、両者の共通witnessだけがない例を別の`filter_diagnosis`にする。
- Bool 2変数の4 contextを、facts/constraintsの真偽4cellへ各1件ずつ分け、各最初のwitnessを保持する。
- 同じguard witnessがfactsとconstraintsの両方で失敗した場合、単一原因と断定しない。
- enabled 2 / effective 0の常時抑止と、enabled 2 / effective 1の一部抑止を区別する。常時抑止はscope期待にかかわらずattention。
- factsとconstraintsを同時に満たすcontextが0なら、`expected_inactive`があっても`BASE_INCONSISTENT`。
- `expected_in_scope`なのにenabled 0、`expected_inactive`なのにenabled > 0、`unspecified`または期待なしのenabled 0をそれぞれattentionにする。
- scope expectationsの外部hash欠落・不一致、別Core、別scope、rule欠落・追加・重複、候補JSONの混入を拒否する。
- format/model hash、各case、段階件数、witness、4cell、診断、hint、attentionの改ざんを独立checkerが拒否する。
- expectation付き/なしの証拠を相互に読み替えず、旧reachability証拠も新形式として拒否する。
- producerの比較境界を意図的に`>=`から`>`へ壊した証拠をcheckerが拒否し、checkerがproducer/旧reachabilityをimportしないことを検査する。
- `max_contexts`の不正型・範囲、全積超過、証拠byte上限、証拠出力によるmodel/expectations上書きを安全側に拒否する。

実行した確認:

```text
python3 -m unittest tests.test_staged_reachability tests.test_staged_reachability_cli -q
OK

python3 -m unittest discover -s tests -q
OK

python3 -m compileall -q rulekernel tests
exit 0
```

並行統合中にテストが追加されていたため、最終総件数はこの記録では断定しない。
上の専用module、全suite、compileallが成功したことと、固定fixtureの数値を受入根拠にする。

## 残る境界

- T03.1はT05 expectationsの外部hash、Core/scope hash、全rule分母を検査するが、task/candidate/review/source manifestの中身を再検査しない。原文からのchainは`verify-interpretation`を併用する。
- `expected_inactive`はホストレビューに依存する。結果と一致しても、有限scopeの選び方、対象外判断、原文の意味、法律上の正しさを証明しない。
- range hintは単純な原子整数比較だけ。一般の論理矛盾、複合式の範囲外理由、最小原因、修正案を計算しない。
- 全列挙できる`finite-decisions/1`だけが対象。モデル1 MiB、証拠8 MiB、全積10,000状況の上限を維持し、factsで絞っても全積を省略しない。
- checkerは別の列挙・式評価・override解決を使うが、Core validator、scope expectation consumer、JSON/hash、Pythonと標準ライブラリは共通信頼対象。健全性の機械証明は未実施。
- 保存fixtureは架空原文とCodex作成のhost reviewであり、ユーザーや法律専門家の承認記録ではない。実法令の意味検査はまだ行っていない。
