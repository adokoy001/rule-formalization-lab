# T07 刑法41条の限定的手書き解釈pack 検証記録

実施日: 2026-09-16
対象: `examples/interpretations/penal-code-41/`

## 目的と範囲

保存済み刑法41条の1 source unitを、T05の手書き解釈IRとT03.1の段階別到達可能性へ接続した最初の実法令fixtureである。対象とする原文上の帰結は「十四歳に満たない者の行為は、罰しない。」だけとし、出力をoptional Boolean `article41_under14_nonpunishment_applies`へ限定した。

この記録は固定原文、手書きcandidate、開発fixtureのreview、有限Core及び証拠の整合性を確認したもの。法律専門家による意味レビュー、個別事件の法的判断、刑法全体の意味検査ではない。保存reviewは`manual_fixture_review` / `CODEX_T07_FIXTURE_AUTHOR`であり、`verify-interpretation --json`は`review_method: manual_fixture_review`と`provisional: true`を返す。pack READMEとreviewにも暫定状態を明記した。

## 固定した入力と解釈

- 原文: 改正履歴ID `140AC0000000045_20260521_507AC0000000039`、施行日 `2026-05-21`、本則`ARTICLE_41`。
- source unit ID: `d7e82dbc6df76bb2ae495e8de02aaf979eb907838c771dc47e550fbabbba23b7`。
- 入力: `age_at_act_years` = 13〜15、`age_at_act_status` = established / unknown、`act_time_status` = established / unresolved。全積は12状況で、factsとconstraintsは空。
- 規則: 両statusがestablishedかつ`age_at_act_years < 14`のときだけ、出力をdefined `true`にする。
- 年齢数値は、statusがestablishedなら行為時点について既に認定された満年齢として受け取る。出生日時からの法的年齢計算や事実認定はしない。不確定status時の数値は有限列挙用carrierとして結論に使わない。
- 出力がabsentでも、処罰可能性、犯罪成立、責任一般又は有罪を導かない。他条、少年法その他の法令もこのpackからは推論しない。

host reviewには12 Cartesian状況をgoldとして固定した。主要な境界は次のとおり。

| 行為時満年齢 | 年齢status | 行為時status | `article41_under14_nonpunishment_applies` |
|---:|---|---|---|
| 13 | established | established | defined `true` |
| 14 | established | established | absent |
| 15 | established | established | absent |
| 13〜15 | unknown | established / unresolved | absent |
| 13〜15 | established | unresolved | absent |

## 固定hash

以下はcanonical JSON SHA-256。`task.json`、`candidate.json`、`review.json`及び`scope-expectations.json`は読みやすいpretty JSONなので、ファイルバイトのSHA-256とは区別する。`compiled.json`、`core.json`、`staged-reachability.certificate.json`はcanonical bytesで保存され、表の値がファイルSHA-256とも一致する。

| 対象 | SHA-256 |
|---|---|
| source bundle | `60da7e094d2a8a7d5b1dbb7addf93e9af5ff573fa6cc56f430b499e7b9003060` |
| task | `80033d3e3b63557599a69c51203f53a41f6338bba51e113380a697af8053ced6` |
| candidate | `aa19598ba55abc7038438f7d2048d333590e9365b5978f936bebb2b72f847674` |
| host review | `944d00c39ec70ba49675e033a44494f3a31e4f10c71566441cfd3edab85171e3` |
| interpretation snapshot | `0ae13f3b8849bae5314aa5ff63dc6cdc42f85c16f831e0afa415b0a20c2da835` |
| finite scope | `4ab59b5ee1910e9c3927a2a2a764186e4a1d4c434112f8729c067c32f4b8a9cc` |
| scope expectations | `fcf9f74b059bf44b9cca8763a348ded6e19661e90f7fbe1b240ff1a17f3205b8` |
| Core model | `2f19f4892263e64319a1592f53677e96ab4140402dd5f9fadc9bf4ff1615f1af` |
| compiled package | `e4a2a41eb531715f2c9ad0732f0b447a77e23c039273ae3d655d87ec17c7b95c` |
| staged certificate | `e5ff411f57fdeb2341dc7e2f24c6530eadd051a35e846910206c2a9616a41406` |

## 独立再検査

保存済み原文、解釈chain、段階別証拠を次の3コマンドで別々に検査した。

```bash
python3 -m rulekernel verify-source \
  examples/sources/penal-code-41/source-spec.json \
  examples/sources/penal-code-41/bundle \
  --expected-bundle-sha256 60da7e094d2a8a7d5b1dbb7addf93e9af5ff573fa6cc56f430b499e7b9003060 \
  --json

python3 -m rulekernel verify-interpretation \
  examples/interpretations/penal-code-41/task.json \
  examples/interpretations/penal-code-41/candidate.json \
  examples/interpretations/penal-code-41/review.json \
  examples/interpretations/penal-code-41/scope-expectations.json \
  examples/interpretations/penal-code-41/compiled.json \
  --source-spec examples/sources/penal-code-41/source-spec.json \
  --source-bundle examples/sources/penal-code-41/bundle \
  --expected-source-bundle-sha256 60da7e094d2a8a7d5b1dbb7addf93e9af5ff573fa6cc56f430b499e7b9003060 \
  --expected-review-sha256 944d00c39ec70ba49675e033a44494f3a31e4f10c71566441cfd3edab85171e3 \
  --expected-scope-expectations-sha256 fcf9f74b059bf44b9cca8763a348ded6e19661e90f7fbe1b240ff1a17f3205b8 \
  --expected-package-sha256 e4a2a41eb531715f2c9ad0732f0b447a77e23c039273ae3d655d87ec17c7b95c \
  --json

python3 -m rulekernel verify-reachability-staged \
  examples/interpretations/penal-code-41/core.json \
  examples/interpretations/penal-code-41/staged-reachability.certificate.json \
  --scope-expectations examples/interpretations/penal-code-41/scope-expectations.json \
  --expected-scope-expectations-sha256 fcf9f74b059bf44b9cca8763a348ded6e19661e90f7fbe1b240ff1a17f3205b8 \
  --json
```

結果:

- `verify-source`: `VERIFIED`、offline、外部source bundle hash一致。
- `verify-interpretation`: exit 0 / `LOWERING_VERIFIED`、Core規則1、host gold 12、coverage selected 1 / unresolved 0 / excluded 0、`HOST_REVIEW_RECORDED`。review methodは`manual_fixture_review`、`provisional: true`。
- `verify-reachability-staged`: exit 0 / `VERIFIED`。total/facts/constraints/admittedは12/12/12/12。唯一の規則はguard/enabled/effective 1/1/1、witnessは13歳・両status established、`expected_in_scope`と一致しattention 0。

`verify-interpretation`は原文manifestからCore、provenance、review binding及びhost goldを再構成する。`verify-reachability-staged`は渡されたCoreの12状況とscope期待を再構成するが、source/task/candidate/review chainを再検査しない。そのため、T07の完了条件では両chainの成功を別々に要求した。

## 負例と境界

- 13/14/15歳と二つのstatusを組み合わせたhost gold 12件を固定し、13歳・両status establishedだけがdefined `true`となることを検査した。
- `age_at_act_years < 14`を誤って`<= 14`へ変え、変更後のhash chainを自己整合に更新しても、14歳gold `G_14_EST_EST`との不一致を独立checkerがexit 1 / `SEMANTIC_MISMATCH`として拒否し、packageを生成しない。
- 年齢status又は行為時statusのgateを1つずつ削った変異も、該当するunknown/unresolved goldにより`SEMANTIC_MISMATCH`となる。
- taskのfactsへ同じ`age_at_act_years`に13と14を同時指定する変異は、exit 2 / `INPUT_INCONSISTENT`となりpackageを生成しない。通常fixtureではfactsを空にし、年齢未知は`age_at_act_status = unknown`として矛盾とは分ける。
- 認定済み満年齢という仮定をhost reviewのaccepted assumptionsから外した変異は、exit 1 / `MODEL_INCOMPLETE`となる。
- optional出力はtrueだけを生成する。14歳以上又は入力が未確定な場合のabsentをfalseへ読み替えず、広い法的結論を出す出力も定義しない。
- review methodを`human_review`へ変えてhash chainを再構築した表示契約の対照例は`provisional: false`になる。`false`も法的意味の正しさ、レビュアー本人性又はT07 fixtureへの人レビューを証明しない。
- 専用回帰`tests/test_penal_code_41_interpretation.py`は、保存chain、12 gold、狭いtrue-only出力、段階件数、外部anchor、`lt`→`le`・二つのgate削除・仮定削除・矛盾factsを含む9件が合格した。`human_review`時の`provisional: false`は解釈IR共通テストで確認する。全suite総数は並行変更で変わるため、この記録には固定しない。

## 到達した範囲と次の課題

T07は、1条文、1 source unit、1十分条件、1規則、1 optional出力、12有限状況の限定profileとして完了した。固定入力からCoreと来歴を再構成し、境界goldと段階別全列挙証拠を検査できる。

原文の意味対応そのものは開発fixture作者の仮の読みで、法的正しさは未確認。生年月日からの年齢計算、他条・他法令、事実認定、責任・犯罪成立・有罪、刑法全体の棚卸しや意味検査も範囲外である。

次のT08は実法令を広げず、架空規範を使って義務・禁止・明示的許可をdecisionとは別の最小意味論として定義する。まず時間なしの有限状況と行動候補で、履行可能性、背景だけによる行動不能、許可が義務にならないことを固定する。
