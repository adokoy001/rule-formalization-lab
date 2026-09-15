# 刑法41条の限定的手書き解釈

T07の最小fixture。e-Gov法令APIから保存した刑法41条の1 source unitだけを対象に、原文から有限Coreまでのhash chainと段階別到達可能性証拠を固定した。

固定原文（本文中の引用）:

> 十四歳に満たない者の行為は、罰しない。

[保存済みsource package](../../sources/penal-code-41/)は、刑法の改正履歴ID `140AC0000000045_20260521_507AC0000000039`、施行日 `2026-05-21`、source unit ID `d7e82dbc6df76bb2ae495e8de02aaf979eb907838c771dc47e550fbabbba23b7`を固定している。

## このpackが表すこと

入力は行為時点の満年齢を運ぶ `age_at_act_years`（13〜15）、その年齢が認定済みかを表す `age_at_act_status`、行為時点が確定済みかを表す `act_time_status` の12 Cartesian状況である。factsとconstraintsは置かない。

唯一の規則は、両statusが `established` であり、かつ `age_at_act_years < 14` のときだけ、optional Boolean出力 `article41_under14_nonpunishment_applies = true` を与える。逆方向の規則も `false` を与える規則もない。

| 行為時点満年齢 | 年齢status | 行為時点status | 期待する出力 |
|---:|---|---|---|
| 13 | established | established | defined `true` |
| 14 | established | established | absent |
| 15 | established | established | absent |
| 13〜15 | unknown | established / unresolved | absent |
| 13〜15 | established | unresolved | absent |

`absent`は「刑法41条のこの限定帰結をこのpackからは導けない」という意味だけである。14歳以上が処罰可能、犯罪成立、責任あり又は有罪だとは意味しない。出生日時からの法的年齢計算、事実認定、他条・他法令も扱わない。不確定statusのときの数値は有限全列挙用のcarrier値であり、結論に使わない。

## ファイル

- [`task.json`](task.json): 保存原文hash、有限scope及び許可された変換範囲を所有するホストtask。
- [`candidate.json`](candidate.json): 1十分条件と4明示仮定を含む手書きの非信頼candidate。
- [`review.json`](review.json): 全4仮定、1 provision、12 Cartesian goldを受諾したホストreview。
- [`scope-expectations.json`](scope-expectations.json): 唯一のCore ruleを `expected_in_scope` とするホスト管理期待。
- [`compiled.json`](compiled.json): 独立checker通過後のCore、source/review/scope binding及び来歴。
- [`core.json`](core.json): compiled packageからcanonical JSONで取り出した段階別検査対象Core。
- [`staged-reachability.certificate.json`](staged-reachability.certificate.json): 全12状況の段階別列挙証拠。

このreviewは `manual_fixture_review` / `CODEX_T07_FIXTURE_AUTHOR` による開発fixtureの点検であり、法律家又はユーザーによる意味承認ではない。`compile-interpretation --json` と `verify-interpretation --json` はそのため結果に `review_method: manual_fixture_review` と `provisional: true` を含める。`LOWERING_VERIFIED` は固定された手書き解釈からCoreへの変換とhost goldの一致を表し、原文の正しい法解釈を証明しない。

## 固定hash

以下は、外部anchorとpackage bindingで使うcanonical JSON SHA-256である。pretty-printされたauthoring JSONのファイルバイトhashとは区別する。

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

段階別結果は、全積12、facts適合12、constraints適合12、admitted 12である。規則はguard 1、enabled 1、effective 1で、13歳・両status establishedがwitnessとなる。scope expectationは一致し、attentionは0件である。

## オフライン再検査

repo rootで次を実行する。最初のコマンドは保存済み原文を外部bundle hashに結び、後二つは解釈chainと段階別証拠を別々に検査する。

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
