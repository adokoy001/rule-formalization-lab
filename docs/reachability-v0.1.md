# 規則の到達可能性診断 v0.1

2026-09-15。T03の実装契約。モデルは既存の
[`finite-decisions/1`](kernel-v0.1.md)をそのまま使う。
自然文を手書きモデルへ写した意味の正しさは、この検査の対象外。

## 調べること

factsと背景制約を満たすadmitted contextについて、各規則の条件が成立した
`enabled_count`と、明示的な例外を解決した後の`effective_count`を別に数える。
件数は人物の数ではなく、宣言された入力値の組合せの数。

| classification | 条件 | 意味 |
|---|---|---|
| `unreachable` | enabled = 0 | この入力・背景・宣言範囲では条件が成立しない |
| `always_suppressed` | enabled > 0、effective = 0 | 条件は成立するが、有効な例外で常に抑制される |
| `partially_suppressed` | 0 < effective < enabled | 条件成立時の一部だけで有効になる |
| `always_effective_when_enabled` | effective = enabled > 0 | 条件が成立した状況では必ず有効になる |

最後の分類は「すべての状況でenabled」を意味しない。どの分類も、その規則が
法的・業務的に正しいことの保証ではない。特に、常に抑制された規則を不要と
断定したり削除したりしない。例外の変更・削除で復活する可能性がある。
決定の衝突・required出力のgapは別の既存照会で検査する。

この版の`unreachable`は、admitted contextでenabledが0という一つの結果だけを表す。
宣言したCartesian積でguard自体に成立例がない場合と、guardの成立例がfactsまたは背景制約で
全て除外される場合を区別しない。また、`age >= 26`を年齢0〜25の範囲で調べた結果と、
一般の論理的矛盾を同一視できない。CLIはこの未分類の注意対象を保守的にexit 1とする。
理由別の段階件数と、原文・packに結び付く明示的なscope期待は、旧証拠を読み替えず[T03.1の別形式](staged-reachability-v0.1.md)として実装した。この文書の旧形式とCLIは互換経路として維持する。

`enabled`と`effective`の意味は既存版から変更しない。

```text
enabled(r,c) = guard(r,c)
effective(r,c) = enabled(r,c)
                 ∧ ∧{¬effective(s,c) | s explicitly overrides r}
```

推移的なoverrideは追加しない。R3→R2→R1で全部enabledなら、R3とR1が有効に
なる。規則配列の順やIDの辞書順を優先順位として扱わない。

## APIと証拠

```python
from rulekernel.reachability import analyze_reachability
from rulekernel.reachability_checker import verify_reachability

certificate = analyze_reachability(model, max_contexts=10000)
result = verify_reachability(model, certificate, max_contexts=10000)
```

`analyze_reachability`は未検査の証拠を返す。`verify_reachability`は期待する
モデルを別に受け取り、全contextと集計を独立に再計算する。

証拠のformatは`finite-decisions-reachability-certificate/1`。
既存の衝突・gap証拠をこの形式として読み替えない。以下のキーが全て必須で、
未知キーは拒否する。

```text
format, profile, model_hash, engine_version,
total_contexts, admitted_contexts, total_rules, cases, rules
```

- `profile`: `finite-decisions/1`
- `engine_version`: `0.1.0`
- `model_hash`: 原文sourceや規則配列順も含むモデル全体のcanonical JSONのSHA256。
- `total_contexts`: 全Cartesian積の件数。入力変数が0個なら1件。
- `admitted_contexts`: factsと背景制約を満たす件数。0件なら証拠を返さず`BASE_INCONSISTENT`。
- `total_rules`: 宣言された規則数。0個でも`total_rules=0, rules=[]`と明記する。
- `cases`: 既存証拠と同じ形の`index, input, admitted, enabled, effective`。
  排除されたcontextも全件保持し、そのenabled/effectiveは空配列とする。
- `rules`: ID辞書順の診断配列。全規則を一度ずつ含む。

各診断の形は次の通り。

```json
{
  "rule_id": "R1",
  "enabled_count": 2,
  "effective_count": 1,
  "enabled_witness": {"case_index": 0, "input": {"flag": false}},
  "effective_witness": {"case_index": 0, "input": {"flag": false}},
  "classification": "partially_suppressed"
}
```

witnessは、それぞれenabled/effectiveとなる**最初のadmitted context**。
該当件数が0なら`null`。入力変数名は辞書順、Boolはfalse→true、Intは昇順、
Enumは宣言順で、最左の変数が最も遅く変わる。規則ID配列も辞書順とする。
ハッシュは期待モデルとの結び付けであり、署名や作成者の真正性の保証ではない。

検査に成功した結果は以下のキーを持つ。

```text
status="VERIFIED", checker_version="0.1.0",
model_hash, certificate_hash, total_contexts, admitted_contexts,
total_rules, rules
```

`rules`はcheckerが再構成した診断であり、入力証拠の集計をそのまま信用して
返さない。`VERIFIED`は証拠の一致を示し、到達不能・抑制がないという意味ではない。
規則0個も明示して返すが、背景が空なら規則数に関係なく拒否する。

CLIは`reachability MODEL`で生成と独立検査、
`verify-reachability MODEL CERTIFICATE`で保存証拠の再検査を行う。
`reachability`の`--certificate`は独立検査後だけ保存し、モデルと同じパスを拒否する。
`unreachable`または`always_suppressed`があればexit 1、どちらもなければexit 0、
不正・未対応・打切りはexit 2。`partially_suppressed`は意図した例外でも生じるため、
それだけではexit 1にしない。

## 上限とエラー

既存モデル検査、モデル1 MiB、全積10,000、証拠8 MiBの上限を維持する。
全積10,000は列挙のハード上限であり、8 MiBまでに収まる処理可能件数の保証ではない。
factsや背景条件で大半の入力が除外されても、全積の予算は減らない。
`max_contexts`はBoolや浮動小数を含まない1〜10,000の整数。

- モデルの型・構文・参照・矛盾facts・未対応のエラーは既存statusを保持する。
- admittedが0件なら`BASE_INCONSISTENT`。0件の診断を合格として返さない。
- 全積、証拠生成、checkerの期待証拠構築の予算超過は`LIMIT_REACHED`。
- 有効モデルに渡された不正証拠は`CERTIFICATE_INVALID`。
  直接APIへ渡した証拠の8 MiB超過も同status。ファイル読込の上限超過は
  既存loaderの`LIMIT_REACHED`。
- 行の欠落・重複・順序違い、偽のadmitted/例外解決、偽の件数/分類/witness、
  trueと1の型すり替え、モデル・版・scopeの差替えを拒否する。

## 独立性と検証範囲

探索側はCartesian積・再帰的な例外解決、checker側はmixed-radixのindex復号・
式のスタック評価・トポロジカルな例外解決を使う。checkerはreachability探索器、
既存engine、既存checkerの意味評価コードをimportしない。共有するのはモデルの
構文・型検査、JSON、ハッシュと既存の上限定数。

全葉を再検査する方式なので高速化にはならない。機械による健全性の証明は
未実施であり、共有validator・仕様・Python・標準ライブラリ・実行環境に信頼が残る。
テストは[`test_reachability.py`](../tests/test_reachability.py)。
