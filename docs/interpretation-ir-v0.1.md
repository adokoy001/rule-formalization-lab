# 手書き解釈IRとCore変換 v0.1

実装日: 2026-09-15
対象format: `rule-interpretation-task/1`、`rule-interpretation-candidate/1`、`rule-interpretation-review/1`、`rule-scope-expectations/1`、`rule-interpreted-core-package/1`
変換profile: `candidate-to-finite-decisions/1`

## この版が確認すること

T04で固定した原文packageから、LLMを使わない手書きの解釈候補を既存`finite-decisions/1` Coreへ変換する。候補、ホスト側の選択・レビュー、scope期待を別入力にし、次を機械検査する。

- task、candidate、review、scope期待、原文package、生成Coreのhash対応。
- 固定manifestの全source unitに対するcandidate coverageとhost coverage。
- 各候補のsource unit IDと、unit内で一意な正確引用。
- T04 manifestに記録された参照の欠落、状態変更、別unitへの付替え。
- 選択したsource unitから到達する未解決参照、未解決issue、未採用assumption、未選択依存。
- 十分条件を持つ定数decisionと、同じ出力へ明示的な代替値を出すreplacement exceptionだけの決定的変換。
- Core ruleごとのsource unit、コードポイントspan、全文、構造path、変換規則の来歴。
- ホスト側で固定した具体例に対するCoreの結果。
- producerをimportしないcheckerによるCore、来歴、review summary、package全体の再構成。

成功状態`LOWERING_VERIFIED`は、これらの構造・変換・具体例が固定入力と一致したという意味である。自然文の読み方が法的・意味的に正しいことは証明しない。

## 信頼する入力を分ける

### Host task

`rule-interpretation-task/1`はホストが用意する。候補生成者に有限domain、出力、facts、constraintsを選ばせない。

```text
format, task_id
source:
  source_package_format, source_spec_sha256, source_bundle_sha256
  raw_sha256, source_unit_manifest_sha256, document_id, revision_id
allowed_source_unit_ids[]
core_scope:
  title, inputs, outputs, constraints, facts
allowed_provision_kinds[]
conversion_profile
```

`allowed_source_unit_ids`はv0.1では固定manifestの全単位と完全一致しなければならない。部分的なtaskでも、分母となる原文単位をcandidate側で消せないようにする。

### Untrusted candidate

`rule-interpretation-candidate/1`は非信頼入力である。

```text
format, task_id, task_hash, source_unit_manifest_sha256
provisions[], references[], proposed_assumptions[]
unresolved_issues[], coverage[], proposed_tests[]
```

candidateにはreview状態、reviewer、選択結果、対象外判断、scope期待を置けない。未知fieldとして拒否する。`proposed_tests`も参考提案であり、変換gateのgoldには使わない。

各provisionは次を持つ。

```text
id
kind = decision_rule | exception | unresolved
condition_role = sufficient_trigger | necessary_only | not_applicable
source_unit_ids[], source_quotes[]
when, then
overrides[], reference_ids[], assumption_ids[], issue_ids[]
```

引用はsource unit IDごとに一つとし、そのunit本文内で一度だけ現れる必要がある。Coreの`rule.source`と来歴spanはcandidateの引用から作らず、検査済みmanifestのunit全文から作る。

### Host review

`rule-interpretation-review/1`はホスト管理入力であり、candidate hashを固定する。

```text
format, review_id, reviewer_id, review_method, reviewed_at
task_hash, candidate_hash, state
selected_provision_ids[], accepted_assumption_ids[]
coverage_decisions[], semantic_tests[], findings[]
```

`state`は`approved`、`pending`、`rejected`。pendingは`REVIEW_REQUIRED`、rejectedはfinding codeを残して`REVIEW_REJECTED`となり、Coreを公開しない。

`review_method=manual_fixture_review`は手作業で作った開発用gold、`human_review`は人によるレビュー記録を表す。checkerのJSON結果はreviewから`review_method`を返し、前者なら`provisional: true`、後者なら`provisional: false`を返す。これは結果表示だけの追加で、`rule-interpreted-core-package/1`のschema、canonical package、hashは変更しない。`provisional: false`も法的意味の正しさ、記録者本人又はreview時刻の真正性を機械証明しない。保存例はCodexが作った架空fixtureの`manual_fixture_review`であり、ユーザーや法律専門家による承認ではない。

host coverageは全source unitを一度ずつ`selected`、`unresolved`、`excluded`のいずれかにする。selected unitは選択provisionと一致しなければならない。candidateのcoverageをそのまま承認したとは扱わない。

`semantic_tests`は全入力を明記し、指定出力について次の状態を期待する。

```text
absent
defined(value)
conflict(values[])
```

否定逆転、必要条件と十分条件、境界、ただし書の欠落を日本語一般から自動判定したとは主張しない。既知の読み方についてhost review hashと具体例を固定し、Core結果が異なれば`SEMANTIC_MISMATCH`で公開を止める。

### Scope expectations

`rule-scope-expectations/1`もcandidateとは別のホスト入力である。T03.1へ渡す契約として、次を固定する。

```text
task_hash, candidate_hash, review_hash
interpretation_snapshot_sha256
source_unit_manifest_sha256, scope_hash, core_model_hash
rules[]:
  core_rule_id
  expectation = expected_in_scope | expected_inactive | unspecified
  source_unit_ids[], rationale
```

全選択Core ruleを一度ずつ列挙する。T05は期待の記録とhash対応を検査し、到達可能性との一致は[T03.1の別形式](staged-reachability-v0.1.md)で独立証拠化する。T03.1はこのT05 source/review chainを再構築しないため、原文からの来歴を確認する場合は両checkerを併用する。

## 変換できる意味

`condition_role=sufficient_trigger`の`decision_rule`だけを、条件成立時に定数値を出すCore ruleへ変換する。文から逆方向の含意や、条件不成立時の反対値を追加しない。

`exception`は次を全て満たす場合だけ変換する。

- `sufficient_trigger`である。
- 自身の`then`に明示的な決定値がある。
- 選択済みのdecisionまたはexceptionを直接overrideする。
- 対象と同じoutputへ代替値を出す。

「原則を適用しない」だけの文から反対値を作らない。必要条件、同値定義、義務、禁止、許可、期限、裁量、算術、単なる適用除外は、このprofileのdecisionへ読み替えない。`unresolved`と`unsupported_construct`に保持し、選択依存へ入るなら`MODEL_INCOMPLETE`で止める。

assumptionはcandidateの提案をreviewが採用した記録であり、それだけでCoreのfactsやconstraintsを書き換えない。実行意味へ影響する前提はhost taskのscopeにも固定する必要がある。

## 参照と依存closure

T04 manifestが持つ全referenceをcandidateにも同じID、from unit、literal、statusで記録する。resolved referenceのtarget provisionはmanifestのtarget source unitに由来しなければならない。candidateがunresolvedをresolvedへ昇格させることはできない。

v0.1は一つのsource unit内を、独立にレビュー済みの小単位へ再分割する仕組みを持たない。このため、そのunitから一つでもprovisionを選択すると、同じunitを起点にする全referenceと全issueを継承する。未解決参照を未選択dummyへ移して、同じunitの別provisionだけを確定することはできない。resolved referenceも選択provisionへ接続され、参照先provisionが選択されていなければならない。

選択範囲外の単位はhost coverageに状態と理由を残せる。未解決を含むpackageを許可した場合、CLIはcoverage attentionとして終了コード1を返す。

## 生成package

`rule-interpreted-core-package/1`は一つのcanonical JSONとして保存する。

```text
format, origin_kind=interpreted_source
conversion_profile, conversion_definition_sha256, producer_version
bindings:
  source binding
  task/candidate/review/scope/scope-expectations hash
  interpretation_snapshot hash
core, core_model_hash
provenance_map[]
review_summary
scope_expectations
```

各provenance mappingはCore rule ID、candidate provision ID、kind、変換規則ID、manifest由来の全source unitとspan、candidate引用hashを持つ。checkerは件数やhashだけでなく、Core AST、override、source文字列、全来歴を再生成して比較する。

埋込Coreは既存カーネルとの互換性のため`finite-decisions/1`、`origin_kind=authored_core`のままとする。そのCore単体を切り離しても解釈review済みとは表示できない。外側packageの`origin_kind=interpreted_source`、bindings、provenance、scope expectationsと組にして扱う。将来の`finite-rules/1`でnativeな由来種別を追加するまでの互換adapterである。

既存カーネル証拠とは、`certificate.model_hash == package.core_model_hash`をjoin keyにできる。既存Core schemaやT01〜T03証拠形式は変更しない。

## CLIと外部anchor

生成:

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
  --package /tmp/member-eligibility.compiled.json
```

保存例の再検査:

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
  --expected-package-sha256 25b6fd536726dce2420f49776e961cb8bb0b78d41b1b8865608dd0fc2335a112
```

source bundle、review、scope expectationsの外部hashは必須。保存package hashは生成後に別の場所へ記録し、再検査時に指定できる。これにより、各ファイルをまとめて自己整合に書き換えただけの変更を検出する。hash自体を同じ攻撃者が書き換えられる保存方法、reviewer本人性、review時刻の真実性は保証しない。

生成CLIはproducer出力をcheckerで再構成してからだけ保存する。失敗時に部分packageを残さず、既存destinationを置換せず、immutable source bundle内への出力を拒否する。

## 終了状態

| 状態 | 意味 | CLI終了コード |
|---|---|---:|
| `LOWERING_VERIFIED` | 変換とhost gold例を独立再構成 | 0、未解決coverageが残る場合1 |
| `REVIEW_REQUIRED` | host reviewがpending | 1 |
| `REVIEW_REJECTED` | host reviewがfinding付きで拒否 | 1 |
| `MODEL_INCOMPLETE` | 選択依存に未解決・未採用・未選択がある | 1 |
| `SEMANTIC_MISMATCH` | Core結果がhost gold例と異なる | 1 |
| invalid/mismatch/unsupported/limit/IO | 構造・固定入力・処理が確定しない | 2 |

`HOST_REVIEW_RECORDED`は意味対応の状態であり、`LOWERING_VERIFIED`と分けて表示する。JSON結果の`review_method`と`provisional`はreview記録の方法を呼出側へ伝える補助状態で、packageには書き込まず、意味レビューの正しさ又は本人性を認証しない。

## 保存fixture

[架空会員規約](../examples/interpretations/member-eligibility/README.md)は2原文単位、resolved reference 1件、decision 1件、replacement exception 1件、host gold 5件を持つ。0〜25歳、登録状態、利用停止状態の104 Cartesian状況を宣言し、`suspended -> registered`制約後の78状況をCoreで扱う。

主要hash:

- source bundle: `a63021f7766381a75a7cb8b91f285f47122c1f5d3912a2f6132653e91cf4ac32`
- source unit manifest: `800acf9358ff61cf7aecac2e433a011e4eb4bce400b5b23e5ac11c88757f0531`
- task: `27d0f6dfceed5dd86c8bdc6392760e0e5f47b8bdc5165ec1ddbeda13f24dfe16`
- candidate: `2248de5a76bb7ed143cd35b656c653c8d8548ad49d40eae11cda670943fd622d`
- review: `e5e7f865b2195b64057842c70e25b4a78755e1fbaf82061df6c8e64504ad88a0`
- interpretation snapshot: `d761f9440b80e8c5643c1df6e7ac9e53914370874240c1ccf26828dfed892d4b`
- scope: `184a90740204736f0263e9e0365212f9e2a2d5ee6c4e5ff560d8c0a916224a68`
- scope expectations: `51dc9ee5f607d6b93d100872b7f3e38b6fe320440c875780a84d47b47575f5a8`
- Core: `b34744e3ea2d98f73d04d8eef9d5867f8d2a553f67bff50f22369c848e50b6e5`
- compiled package: `25b6fd536726dce2420f49776e961cb8bb0b78d41b1b8865608dd0fc2335a112`

## 保証しないこと

- host reviewと自然文の意味一致、解釈候補の網羅性、法律専門家による確認。
- 日本語一般からの否定、必要十分条件、例外、曖昧性の完全な自動判定。
- reviewer、review時刻、取得時刻の暗号学的な本人性・真正性。
- 義務、禁止、許可、期限、裁量、年齢計算、法的評価。
- 埋込Coreをpackageから切り離した場合の解釈・review情報の保持。
- checkerとproducerが共有するvalidator、JSON/hash、Python処理系の独立性。

T05は「原文を正しく形式化した」と自動認定する機能ではない。誤読を見つけるための分離、固定、具体例、未解決gateを実装した最初の小さな経路である。
