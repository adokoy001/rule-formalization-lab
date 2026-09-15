# 改定差分 v0.1 の実装契約

2026-09-15。比較profileは `finite-decisions-diff/1`、証拠formatは
`finite-decisions-diff-certificate/1`、実装versionは `0.1.0`。
[カーネル契約](kernel-v0.1.md)の有限決定モデル同士を、宣言した全入力で比較する。
自然文の意味、義務・時間、法令間の関係を自動判定するものではない。

## 比較できるモデル

左右とも有効な `finite-decisions/1`・`authored_core` が必要。
`inputs` と `outputs` はcanonical JSONで一致しなければ `UNSUPPORTED`。
型、入力領域、出力領域、required、Enumの宣言順も同一である必要がある。
オブジェクトのキーの並びは問わない。型・領域を広げた改定の比較はこの版の範囲外。
facts、constraints、rules、title、sourceは異なってよい。

入力は変数名辞書順、Boolはfalse/true、整数は昇順、Enumは宣言順で列挙し、
最左の変数を最も遅く変える。入力0変数でも空割当1件を検査する。
各側のadmitted、式、明示overrideの意味はカーネル契約と同じ。
推移的overrideは追加せず、例外への例外で原則が復活する。

## 差分の意味

admittedな側は全outputについて、effectiveな規則IDと重複を除いた結論値を記録する。
IDは辞書順、値はcanonical JSON文字列の辞書順。状態は値0個で`absent`、
1個で`defined`、2個以上で`conflicting`。required=falseのabsentも記録する。

両側admittedなcontextについて、出力ごとに次を集計する。

| kind | 条件 |
|---|---|
| semantic_change | stateまたは値集合が変化 |
| explanation_only | stateと値集合は同じで、effectiveな規則ID集合だけが変化 |
| conflict_introduced | conflicting以外からconflictingへ変化 |
| conflict_resolved | conflictingからそれ以外へ変化 |
| gap_introduced | required出力がabsent以外からabsentへ変化 |
| gap_resolved | required出力がabsentからそれ以外へ変化 |

semantic_changeとexplanation_onlyは同じoutput/contextでは排他的。
introduced/resolvedはsemantic_changeの内訳と重複するため、各件数を足して総変更数にしない。
conflicting→absentはconflict_resolvedとgap_introducedの両方に該当する。
規則配列の並べ替えは差分なし。IDだけの変更はexplanation_only。
同じIDのsource/titleだけが変わった場合はモデルhashが変わるが、これらの照会では検出しない。
ここでいう「説明」はeffectiveなIDの集合に限定し、原文や導出過程の完全な比較ではない。

左右片側だけがadmittedなら`scope_change`に数える。排除した側の出力を評価せず、
semantic_change等には数えない。左右とも非admittedでも全件証拠に残す。
左右どちらかのadmitted総数が0なら`BASE_INCONSISTENT`とし、比較証拠を返さない。
左右がそれぞれ非空でも共通admittedが0という場合は有効な比較であり、scope_changeを明示する。
この場合のsemantic_change=0は同値の主張ではない。

## APIと証拠

- `rulekernel.diff.analyze_diff(left, right, max_contexts=10000) -> certificate`
- `rulekernel.diff_checker.verify_diff(left, right, certificate, max_contexts=10000) -> verification`

以下は構造を示す例であり、実際のcasesとqueriesは省略せず全件を持つ。

```json
{
  "format": "finite-decisions-diff-certificate/1",
  "comparison_profile": "finite-decisions-diff/1",
  "profile": "finite-decisions/1",
  "engine_version": "0.1.0",
  "left_model_hash": "...sha256...",
  "right_model_hash": "...sha256...",
  "total_contexts": 2,
  "left_admitted_contexts": 2,
  "right_admitted_contexts": 2,
  "common_admitted_contexts": 2,
  "cases": [
    {
      "index": 0,
      "input": {"student": false},
      "left": {"admitted": true, "outputs": {"eligible": {"state": "defined", "values": [false], "rule_ids": ["R1"]}}},
      "right": {"admitted": true, "outputs": {"eligible": {"state": "defined", "values": [true], "rule_ids": ["R2"]}}}
    }
  ],
  "queries": [
    {"kind": "scope_change", "output": null, "count": 0, "witness": null},
    {"kind": "semantic_change", "output": "eligible", "count": 1,
      "witness": {"case_index": 0, "input": {"student": false},
        "left": {"state": "defined", "values": [false], "rule_ids": ["R1"]},
        "right": {"state": "defined", "values": [true], "rule_ids": ["R2"]}}}
  ]
}
```

全キー必須、未知キー不可。非admitted側は`{"admitted":false,"outputs":{}}`。
casesは全Cartesian積を列挙順に一度ずつ保持し、indexは0から連番。
queriesはscope_changeを最初に持ち、続けてoutput名辞書順で表のkind順。
gap照会はrequired出力にだけ存在する。出力0個でもscope_change照会を持つ。
各countはcontext件数、witnessは最初の該当contextで、0件ならnull。
scope_changeのwitnessは`case_index,input,left,right`を持ち、left/rightはadmittedのBool。
出力照会のwitnessは同じキーを持ち、left/rightは出力の`state,values,rule_ids`。

verificationは`status:VERIFIED, checker_version:0.1.0, comparison_profile`、
`left_model_hash,right_model_hash,certificate_hash`、上記4個のcontext件数、queriesを返す。
queriesは照合済みの照会にstatusを足したもの。
count>0なら`WITNESS_VERIFIED`、0なら`NO_WITNESS_IN_SCOPE_VERIFIED`。
VERIFIEDは報告の裏付けであって、改定が望ましい、問題なし、原文と対応するという意味ではない。
ハッシュは署名ではなく、呼出し側が指定した期待モデルに証拠を結び付ける。
通常のカーネル証拠を差分証拠として読み替えない。

CLIは`diff LEFT RIGHT`で生成と独立検査、`verify-diff LEFT RIGHT CERTIFICATE`で
保存証拠の再検査を行う。`diff`の`--certificate`は独立検査後だけ保存し、左右の
モデルと同じパスを拒否する。全照会0ならexit 0、何らかの差分があればexit 1、
不正・未対応・打切りはexit 2。exit 1には改善、適用範囲の変化、規則IDだけの変化も
含まれるため、「問題が増えた」という意味ではない。

## 上限と信頼範囲

モデルの構文・型・エラーはカーネルと共通。max_contextsは厳密な整数1〜10,000。
10,000は全Cartesian積の列挙ハード上限であり、差分証拠を10,000状況まで生成できる保証ではない。
factsで範囲を絞っても全Cartesian積で予算判定する。モデルは各1 MiB、差分証拠は8 MiB。
生成・期待証拠再計算のbyte予算超過と列挙予算超過は`LIMIT_REACHED`、
APIに直接渡された不正形式・8 MiB超の証拠は`CERTIFICATE_INVALID`。
部分結果や途中までの「変更なし」を返さない。

チェッカーはdiff/engine/checkerの評価コードをimportせず、独自の混合基数列挙、
式評価、上位からの反復override解決、差分集計で全証拠と厳密一致を確認する。
Boolと整数、全件数、両モデルhash、版、scope、全出力、最初の具体例まで比較する。
Python標準ライブラリだけを利用する。共通validator、canonical JSON、hash、
仕様と実行環境は信頼対象として残り、健全性の機械証明は行っていない。
