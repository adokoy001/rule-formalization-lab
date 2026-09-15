# 自前カーネル v0.1 の実装契約

2026-09-15。実装対象 profile は `finite-decisions/1`。将来の `finite-rules/1` の一部。
Python 3.11+ 標準ライブラリだけを使う。自然文を人が形式化した `authored_core` のみ。

## JSONモデル

トップのキーは全て必須: `profile, origin_kind, title, inputs, outputs, constraints, facts, rules`。未知キーは拒否。
- profile: finite-decisions/1
- origin_kind: authored_core
- title: 空でない文字列
- inputs: 変数名 -> 型。型は {"kind":"bool"} / {"kind":"int","min":0,"max":120} / {"kind":"enum","values":["member","guest"]}。
- outputs: 出力名 -> {"type":型,"required":true/false}。requiredだけで全域性を指定。
- constraints: 真偽式の配列。背景条件。空配列は真。
- facts: {"var":"age","value":18} の配列。同一変数・同値の重複可、異値は INPUT_INCONSISTENT。未指定変数は全有限値を補完する。
- rules: {"id":"R1","source":"架空の原文","when":式,"then":{"output":"eligible","value":true},"overrides":[]} の配列。
  overridesは規則ID配列。自分、重複、未定義targetを拒否、循環はUNSUPPORTED。
- 名前・IDは [A-Za-z][A-Za-z0-9_]{0,63}。
- 空のrulesは有効（required出力はgap）。入力0変数は空割当1件。inputs/outputs各32件まで、rules128件まで。
- 整数の宣言・定数は符号付き64bit範囲（比較のみ、浮動小数なし、boolをintとみなさない）。enumは非空・一意の空でない文字列、最大256値。
- 全ての出力値とfactsは宣言された型・範囲の値。

式は {"var":"age"} / {"const":18} / {"op":"ge","args":[{"var":"age"},{"const":18}]}。
演算は eq/ne/lt/le/gt/ge (2引数)、and/or (2以上)、not (1引数)。
順序比較は整数のみ。eq/neは同種型、enum同士は値集合まで同一、文字列定数はenumの領域内でなければ拒否。
入力だけ参照可、出力参照不可。guard/constraintの最終型はbool。
無限型、算術、量化、定義、義務/禁止/許可、時間、原文自動形式化は未対応。

## 有限意味論

変数名の辞書順でCartesian積を列挙する。boolはfalse,true、intは昇順、enumは宣言順。最左の変数が最も遅く変わる。
各状況について全factsとconstraintsが真ならadmitted。admittedが0なら BASE_INCONSISTENT（合格にしない）。
未入力はfalseではなく全補完。衝突した結論を背景制約へ移さない。

enabled(r,c) = guard(r,c)
effective(r,c) = enabled(r,c) AND NOT any(effective(s,c) for s that explicitly overrides r)
DAGで評価し、推移的なoverrideは追加しない。R3 -> R2 -> R1で全enabledならR3とR1がeffective。
同一outputへ異なる値が2個以上ならconflict。同じ値の重複はconflictでない。
required=trueのoutputにeffectiveな値が0ならgap。衝突はgapと別。

## 共通API

`rulekernel.model`:
- `KernelError(status, message)`。属性status,message。
- `validate_model(model) -> None`。型・キー・参照・DAG・fact矛盾検査。
- `canonical_json(obj) -> str`。ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False。
- `digest(obj) -> str`。上記UTF-8のSHA256。
- `load_json(path, max_bytes=...) -> object`。重複キー、NaN/Infinity、不正UTF-8拒否。
- `MAX_CONTEXTS=10000`, `MAX_CERTIFICATE_BYTES=8*1024*1024`。
- モデルは呼出しの間書き換えない。共有するのはこの構文・型validator、JSON、ハッシュのみ。

`rulekernel.engine.analyze(model, max_contexts=10000) -> certificate`:
全積が予算超過なら LIMIT_REACHED。部分結果でabsenceを返さない。admitted=0なら BASE_INCONSISTENT。
独立checkerを呼ばずに証拠を作る。

`rulekernel.checker.verify(model, certificate, max_contexts=10000) -> verification`:
探索器・探索側の式評価/例外解決/レポート集計をimportしない。独立の列挙・式評価・例外解決・集計で全証拠を再検査。
有効モデルの不正証拠は CERTIFICATE_INVALID。大き過ぎる探索範囲は LIMIT_REACHED。モデル由来のエラーはそのまま。
例外ではなく空集合を合格させることは禁止。

## 証拠 (全キー必須、未知キー拒否)

```json
{
  "format": "finite-decisions-certificate/1",
  "profile": "finite-decisions/1",
  "model_hash": "...sha256...",
  "engine_version": "0.1.0",
  "total_contexts": 4,
  "admitted_contexts": 4,
  "cases": [
    {"index": 0, "input": {"age": 18, "student": false}, "admitted": true, "enabled": ["R1"], "effective": ["R1"]}
  ],
  "queries": [
    {"kind": "conflict", "output": "eligible", "count": 1, "witness": {"case_index":0,"input":{"age":18,"student":false},"rule_ids":["R1","R2"],"values":[false,true]}},
    {"kind": "gap", "output": "fee_yen", "count": 1, "witness": {"case_index":0,"input":{"age":18,"student":false},"rule_ids":[],"values":[]}}
  ]
}
```

上例cases/queriesは形の説明用。実データは全contextを保持し、queryは全outputのconflictとrequired出力のgapを必ず持つ。
- indexは0から連番。casesは背景で排除されたものも含め全Cartesian入力を一度ずつ順に保持。
- admitted=falseのcaseはenabled/effectiveとも空配列。
- enabled/effective/rule_idsはID辞書順。valuesは重複排除後canonical_json文字列の辞書順。
- queriesはoutput名辞書順、各outputについてconflict、requiredならgapの順。
- countは該当するadmitted contextの数。witnessは最初の該当context、0件ならnull。
- checkerは列挙漏れ、ID重複、型すり替え（trueと1）、偽の集計、hash/version/scope差替えを拒否する。
- certificateのハッシュは署名/真正性の証明ではない。checkerへ利用者が指定する期待モデルに結び付ける。

verificationの構造:
```json
{
  "status": "VERIFIED",
  "checker_version": "0.1.0",
  "model_hash": "...",
  "certificate_hash": "...",
  "total_contexts": 4,
  "admitted_contexts": 4,
  "queries": [
    {"kind":"conflict","output":"eligible","count":1,"witness":{},"status":"WITNESS_VERIFIED"}
  ]
}
```
count=0ならstatusはNO_WITNESS_IN_SCOPE_VERIFIED。VERIFIEDは検査結果の裏付けであり、問題がないという意味ではない。

これは直接Core列挙の全葉を平坦な配列にした証拠。探索木を圧縮する機能はまだない。checkerも全域を走査するため高速化にはならない。
健全性の機械証明は未実施。共通validator・仕様・Python・標準ライブラリ・実行環境の誤りは信頼対象として残る。


## エラー、上限とCLI

- MODEL_INVALID: 型、必須キー、参照、空領域、不正JSONなど。
- UNSUPPORTED: profile/origin/演算/未知キー/override循環など、この版で受け付けない構成。
- INPUT_INCONSISTENT: 同じ入力へ異なる値のfacts。
- BASE_INCONSISTENT: 全有限入力のうち背景・factsに合うものが0件。
- LIMIT_REACHED: 入力/式/証拠/列挙数が上限超過。完了した証拠を返さない。
- CERTIFICATE_INVALID: 期待モデルの完全な再評価と証拠が一致しない。
- IO_ERROR: CLIの読書き失敗。

max_contextsは1..10,000の整数で、10,000はCartesian積の列挙ハード上限。モデル1 MiB、証拠8 MiBの上限も独立に適用するため、10,000状況の証拠を常に生成できるという契約ではない。式は全モデルで8,192ノード・深さ32、and/orは2〜64引数、背景128式、facts1,024件まで。title256文字、source8,192文字、Enum値/文字列定数256文字まで。上限は契約の一部で、黙って切り詰めない。

証拠APIに直接渡された8 MiB超の証拠はCERTIFICATE_INVALID、ファイル読込・証拠生成・checkerの期待証拠構築の予算超過はLIMIT_REACHED。モデルのJSON loaderは復号後の孤立サロゲートも拒否する。

CLI checkはanalyze→verifyの順で動く。verifyは探索器を実行せず保存証拠を独立再評価する。結果が検査できた場合だけ、checkの--certificateで指定したパスへ原子的に保存する。指定パスの既存証拠は置き換える。モデル入力と同じパスへの出力は拒否する。失敗した実行では、以前保存した証拠は更新されない。

終了コード: 0は全照会で検出なし、1は照会に問題の具体例あり、2は確定不能。出力0個のモデルには照会0件と明示する。JSON結果のVERIFIEDを「問題なし」という意味で利用しない。
