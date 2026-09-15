# 段階別到達可能性診断 v0.1

2026-09-15。T03.1の実装契約。対象モデルは既存の
[`finite-decisions/1`](kernel-v0.1.md)で、T03の
[`finite-decisions-reachability-certificate/1`](reachability-v0.1.md)は変更しない。
新しい証拠形式は`finite-decisions-staged-reachability-certificate/1`である。

この診断は、規則が指定された有限範囲のどの段階で成立例を失うかを数える。
原文の正しい読み方、法的な適用範囲、規則を削除してよいかは判定しない。

## 段階の意味

宣言した入力のCartesian積を`D`、factsへの適合を`F(c)`、全constraintsへの適合を
`C(c)`、規則`r`の条件を`G(r,c)`とする。各規則について次を全件数え、件数が正なら
辞書順の有限列挙で最初のwitnessも保存する。

| 証拠field | 数える条件 |
|---|---|
| `guard_count` | `G(r,c)` |
| `guard_and_facts_count` | `G(r,c) ∧ F(c)` |
| `guard_and_constraints_count` | `G(r,c) ∧ C(c)` |
| `enabled_count` | `G(r,c) ∧ F(c) ∧ C(c)` |
| `effective_count` | enabledであり、明示overrideの解決後も有効 |

`filter_partition`はguardが真のcontextを、`facts_match`と`constraints_match`の
`(true,true)`, `(true,false)`, `(false,true)`, `(false,false)`の順で4分割する。
各cellに件数と最初のwitnessを持つため、factsとconstraintsが同じcontextを除外した場合や、
それぞれには成立例があるが共通のenabled例がない場合を、単純な件数差から一原因へ決め付けない。

証拠全体には`total_contexts`、`facts_matching_contexts`、
`constraints_matching_contexts`、`admitted_contexts`も含む。
`admitted_contexts = 0`ならscope期待に関係なく`BASE_INCONSISTENT`とし、
全規則を意図的inactiveとして成功させない。

overrideの意味は既存Coreと同じである。

```text
enabled(r,c) = G(r,c) ∧ F(c) ∧ C(c)
effective(r,c) = enabled(r,c)
                 ∧ ∧{¬effective(s,c) | s explicitly overrides r}
```

推移的なoverride辺は補わない。例外への例外では原則が復活しうる。

## 診断ラベル

`activation_stage`は次の順で決める。

| 値 | 条件 |
|---|---|
| `no_guard_witness_in_declared_domain` | guard = 0 |
| `no_enabled_witness_after_scope_filters` | guard > 0、enabled = 0 |
| `always_suppressed` | enabled > 0、effective = 0 |
| `partially_suppressed` | 0 < effective < enabled |
| `always_effective_when_enabled` | effective = enabled > 0 |

`filter_diagnosis`は、guard成立例がない、scope filter後にもenabled例がある、factsだけで
全例が止まる、constraintsだけで全例が止まる、両方がそれぞれ全例を止める、または
両filterに個別の成立例はあるが共通例がない、を区別する。これは有限列挙結果の説明であり、
原文上の原因や修正箇所を特定するものではない。

`range_hint`はguard成立0のとき、単一の整数変数と整数定数の`eq/ne/lt/le/gt/ge`比較が
宣言整数範囲と非交差であることを直接確認できた場合だけ付ける。
例えばage 0〜25に対する`age >= 26`にはhintが付くが、
`flag and not flag`には付かない。一般のBoolean式を論理矛盾と範囲外へ完全分類した結果ではない。

互換表示用の`legacy_classification`も再計算するが、旧証拠を新形式として受理しない。

## scope expectationsとの接続

T05の`rule-scope-expectations/1`は任意入力である。指定する場合は
`--expected-scope-expectations-sha256`も必須で、canonical JSONのSHA-256、
`core_model_hash`、Coreのtitle/inputs/outputs/constraints/factsから作る`scope_hash`、
全Core rule IDを一度ずつ含む固定分母を検査する。証拠の
`scope_expectations_binding`にはexpectation IDとtask/candidate/review/source manifest/
interpretation snapshot/scope/Coreの各hashを保持する。

T03.1のconsumerは、これらT05由来hashの形式とexpectations全体の外部hashへの結合を確認するが、
原文package、task、candidate、review、interpretation snapshotを読み直さない。
source unit IDが実際のmanifestに存在することやreview chain全体を確認するには、同じ入力束を
[`verify-interpretation`](interpretation-ir-v0.1.md)でも検査する。

期待値はenabled、つまりoverride前の成立性と照合する。

| host expectation | enabledとの一致 | 結果 |
|---|---|---|
| `expected_in_scope` | enabled > 0 | `matched_in_scope` |
| `expected_in_scope` | enabled = 0 | `EXPECTED_IN_SCOPE_NOT_REACHED` |
| `expected_inactive` | enabled = 0 | `matched_inactive` |
| `expected_inactive` | enabled > 0 | `EXPECTED_INACTIVE_BUT_REACHED` |
| `unspecified`または期待入力なし | enabled = 0 | `INACTIVE_WITHOUT_EXPECTATION` |

enabled > 0かつeffective = 0は、expectationとは別に常に`ALWAYS_SUPPRESSED`とする。
したがって`expected_inactive`で常時抑止を正常扱いにはできない。

`expected_inactive`は、ホストが選んだ原文解釈と有限scopeについてのレビュー判断である。
機械検査が`matched_inactive`を返しても、そのscope選択が正しいこと、対象外にしてよいこと、
原文や法律上も非適用であることは証明しない。期待を付けない旧利用経路も残し、
その場合の非到達は従来どおり注意対象にする。

## 証拠と独立checker

証拠の最上位fieldは次のとおり。

```text
format, profile, model_hash, engine_version,
scope_expectations_binding,
total_contexts, facts_matching_contexts,
constraints_matching_contexts, admitted_contexts,
total_rules, cases, rules, attention
```

各`cases`行は`index, input, facts_match, constraints_match, admitted, guard, enabled,
effective`を持つ。facts/constraintsで除外されたcontextも省略せず、guardの真偽は保持し、
enabled/effectiveは空配列にする。入力変数名は辞書順、Boolはfalse→true、Intは昇順、Enumは
宣言順で、最左の変数が最も遅く変わる。

各`rules`行は段階ごとの件数・witness、4分割、診断、hint、旧分類、scope expectation、
expectation結果、attention codeを持つ。`attention`はrule ID、code、固定説明を平坦に列挙する。

生成側は`itertools.product`と再帰式評価、memo化したoverride解決を使う。
checkerはmixed-radixのindex復号、反復式評価、トポロジカルなoverride解決で全context、全行、
全witness、全集計、全attentionを独立に再構成し、canonical JSON全体が一致しなければ
`CERTIFICATE_INVALID`とする。checkerはstaged producer、既存engine/checker、旧reachability
実装をimportしない。Core validator、JSON/hash、上限、scope-expectation consumer、Python処理系と
標準ライブラリは共通信頼対象であり、健全性の機械証明は未実施である。

## CLI

```bash
python3 -m rulekernel reachability-staged MODEL \
  --scope-expectations SCOPE_EXPECTATIONS \
  --expected-scope-expectations-sha256 EXTERNAL_SHA256 \
  --certificate NEW_CERTIFICATE

python3 -m rulekernel verify-reachability-staged MODEL CERTIFICATE \
  --scope-expectations SCOPE_EXPECTATIONS \
  --expected-scope-expectations-sha256 EXTERNAL_SHA256
```

expectationsを使わない場合は二つのscope optionをどちらも省略する。片方だけの指定、古いhash、
別Core・別scope・欠落/余分/重複rule、候補形式の入力はexit 2で拒否する。生成時にexpectationsへ
結んだ証拠を、再検査時にexpectationsなしへ読み替えることもできない。

- exit 0: 独立再検査成功、attention 0。
- exit 1: 独立再検査成功、attention 1件以上。
- exit 2: モデル・期待・証拠の不正/不一致、空background、未対応、上限、I/O失敗で未確定。

証拠出力はモデルとexpectationsへの上書きを拒否し、独立checkerの成功後だけ保存する。

## 上限と保証範囲

既存のモデル1 MiB、証拠8 MiB、全Cartesian積10,000状況を維持する。
facts/constraintsで多数のcontextが除外されても全積の列挙予算は減らない。全contextを証拠へ
保持するため、高速化や大規模処理の方式ではない。実効上限は[T06の固定合成workload](verification-t06-2026-09-15.md)で別に測定した。

この版が確定するのは、指定した`finite-decisions/1`モデルと固定有限domainにおける段階件数、
witness、override結果、外部hash付きexpectationsとの一致だけである。無限領域、一般SAT/UNSAT、
実法令の意味、事実認定、LLM候補生成、reviewer本人性、署名・第三者timestampは対象外。

実装は[`staged_reachability.py`](../rulekernel/staged_reachability.py)、
[`staged_reachability_checker.py`](../rulekernel/staged_reachability_checker.py)、
[`staged_reachability_model.py`](../rulekernel/staged_reachability_model.py)。
回帰は[`test_staged_reachability.py`](../tests/test_staged_reachability.py)と
[`test_staged_reachability_cli.py`](../tests/test_staged_reachability_cli.py)にある。
