# 現在の状態

更新日: 2026-09-16

公開先: [GitHub / adokoy001/rule-formalization-lab](https://github.com/adokoy001/rule-formalization-lab)

ライセンス: [MIT License](LICENSE)（e-Gov由来データは[第三者由来データの通知](THIRD_PARTY_NOTICES.md)を参照）

## 目標

趣味として、現実的な範囲のルールを検証し、穴や不整合に気づく支援ツールを育てる。架空規約を徐々に大きくし、刑法・刑事訴訟法の限定論点、条文群、章へ段階的に広げる。

## できていること

**有限決定・有限規範・有限手続時間の各カーネルを自前実装し、手書きモデルを実際に検査できる。**

- Python標準ライブラリだけの入力検査・全列挙器・独立証拠検査器・CLI。
- Bool、有限Enum、範囲付き整数、比較とBoolean式。
- 未入力の全補完、背景制約、矛盾するfactsの拒否。
- 明示的な例外と原則復活。決定の衝突とrequired出力の欠落。
- 証拠の保存、モデルとの結び付け、全入力・全集計の再検査。
- 6条・52状況の架空規約。問題版は資格衝突4状況・料金gap4状況、修正版は全照会0件。
- 20規則・416状況の拡張教材。問題版は資格衝突32・料金gap32・貸出衝突4、修正版は全照会0件。
- 同じ入出力領域を持つ2モデルの改定差分。scope、意味、規則ID、衝突/gapの発生・解消を区別し、独立checkerで全件を再計算。
- 規則の到達可能性診断。条件不成立、常時抑止、一部抑止、条件成立時常時有効を区別し、独立checkerで全件を再計算。
- 原文package v0.1。capture spec、raw XML、取得記録、抽出text、revision-local source unit ID、コードポイントspan、hash chainをproducer非依存checkerでoffline再構成。`xml-unit-text/2`は本文空白を保持し、e-Govの既知block indentationと正しいRubyだけを限定処理する。
- Unicode架空原文3単位を保存。CRLF、文字参照、ZWJ絵文字、結合文字、同文反復、Ruby/Rt、未解決参照を固定例にした。
- e-Govから版IDを明示した刑法全文XMLと`law_data` metadataを保存し、本則41条1単位を完全な構造pathで抽出。法令種別・元号年・番号・公布日・法令名の同一性fieldも照合する。取得失敗時は新packageを公開せず、既存packageを上書きしない。
- 保存済みbundleは外部に控えたlock hashを指定して再検査できる。新規packageの原子的公開はWSLのLinux filesystemを対象とし、`/mnt/c`は`UNSUPPORTED`。
- 手書き解釈IR v0.1。ホストtask、非信頼candidate、host review、scope expectationsを別形式にし、source package、review、scope、Core、生成packageをhash chainで結ぶ。
- 十分条件の定数decisionと、同じ出力へ代替値を出す明示的replacement exceptionだけを既存`finite-decisions/1`へloweringする。必要条件、義務、禁止、許可、期限、単なる適用除外、未解決依存は変換しない。
- producerをimportしない解釈checkerが、原文manifestからCore、rule単位のprovenance、review summary、host gold 5例、package全体を再構成する。候補自身による承認・対象外指定、stale hash、来歴/Core改ざんを拒否する。
- 2条の架空会員規約を保存。104 Cartesian状況のうち背景制約後78状況を扱い、18歳境界と利用停止例外を2規則へ変換した。source bundle、review、scope expectations、保存packageの外部hash付きoffline再検査が通る。
- 段階別到達可能性診断 v0.1。宣言全域でguard、guard+facts、guard+constraints、enabled、effectiveを分け、facts×constraintsの4cell、各最初のwitness、限定的な整数範囲hintを独立checkerで再構成する。旧reachability v0.1は互換維持。
- T05の外部hash付きscope expectationsをCore/scope/全rule分母へ結び、`expected_in_scope`、`expected_inactive`、`unspecified`と到達結果を照合する。常時抑止、期待外・未指定の非到達、stale入力を情報扱いへ落とさない。
- Club20の第19・20条と同文のT04/T05 fixtureと段階別証拠を保存。52状況でR19はguard/enabled/effective 26、R20は0で、host期待との一致によりattention 0。既存会員規約104状況の段階別証拠も保存した。
- T10反映後の全suite 358件と`compileall`が合格。従来の決定・原文・解釈・規範・ベンチマークに加え、時間境界、観測終了、法源binding、期限起算点、代替行為、改ざんを回帰検査する。
- T06固定合成ベンチマーク。13 Bool・8,192状況、50/100規則、guard 1/8・7/8、background 1・1/8の8 scenarioとrevision、局所/union衝突・override復活sentinelをconfig/generator/manifest/hash付きで保存した。
- 4検査経路をfresh subprocessで測るharnessと正式reportを保存。静的32経路は23件が独立checkerまで`VERIFIED`、9件が証拠8 MiBで`LIMIT_REACHED`。固定100規則・10出力familyではcheck 5,661/5,662、diff 3,172/3,173、reachability 5,646/5,647、staged 3,704/3,705が連続する成功/失敗境界だった。
- 4境界すべてで、最初の`LIMIT_REACHED`がexit 2となり、新しいcertificateを残さず既存targetを変更しないことを実CLIで確認。正式reportのraw/body SHA-256と、16 source binding、10 endpointの現物一致を独立再計算した。
- 保存report専用checkerが外部raw hash、現在のsource/model、密度・集計、raw 3 sample、境界endpoint、report出力と入力pathの分離を再検査し、完了workflow 27・上限到達13として`VERIFIED`を返す。性能値の再実測や環境の第三者証明ではない。
- T07刑法41条の限定的手書き解釈pack。保存済み本則`ARTICLE_41`の1 source unitを、1十分条件・1 optional出力・1 Core ruleへ接続した。13〜15歳、年齢status、行為時statusの12状況で、13歳・両status establishedだけをdefined `true`とし、14歳以上や未確定入力はabsentのまま残す。
- T07の外部anchor付き`verify-interpretation`は`LOWERING_VERIFIED`、host gold 12、coverage selected 1を返す。`manual_fixture_review`は`PROVISIONAL`と明示し、法律専門家の意味承認と区別する。別chainの段階別checkerは12状況、guard/enabled/effective 1/1/1、scope期待一致、attention 0を再構成する。`lt`→`le`と矛盾factsの負例も拒否する。
- T08有限規範カーネル`finite-norms/1`。有限状況とBoolean行動候補を分け、義務・禁止を同時に守れる候補、背景だけの行動不能、明示的許可の行使・非行使候補を全列挙する。producerをimportしないcheckerが全traceと集計を再構成する。
- T08架空fixtureは全8状況、admitted 4、各8行動候補。対象外4、背景不能2、規範上の履行不能1、履行可能1を区別し、`P_C`のusable/nonexercise witnessを各1件保存した。model/certificateの外部hash付き再検査は`VERIFIED`、注意対象ありのexit 1。
- T09有限手続・時間カーネル`finite-procedure-time/1`。最大8個の一回限りslot、`(tick, phase)`、排他的観測終了、包含期限、禁止窓、any-of target、strict/non-strict先後を全列挙し、producer非依存checkerが全traceを再構成する。
- T09架空申請fixtureは16 context。履行可能10、規範不能3、背景不能1、未確定2を分け、期限直前・一致・直後、異なる起算点、同時刻、部分禁止、観測終了前・一致・後を固定した。certificate `4d034bb6...bca7`は外部anchor付き`VERIFIED`、注意対象ありのexit 1。
- T10刑事訴訟法限定pack。現行施行版の55条・203条から206条を5 source unitとして保存し、203条の48時間、205条の受領後24時間と拘束後72時間を13 contextで別々に診断する。公訴提起は勾留請求とのany-of、送致手続と受領は別eventである。
- T10 binding checkerは全文quote、unit ID、coverage全5件、task/candidate/review、model、certificateを独立再構成し、外部anchor付き`MANUAL_MODEL_BINDING_VERIFIED`を返す。reviewは`manual_fixture_review` / `provisional: true`で、semantic loweringと法的結論はfalseである。
- 206条事情主張は数値超過を自動延長せず、釈放規定のtriggerと実際の釈放観測も別診断にした。未知の権限・裁量・一般暦等は既存意味へ読み替えない。T06 report checkerも外部hash付きで`VERIFIED`を維持した。

[使い方](README.md)、[有限手続・時間仕様](docs/procedure-time-kernel-v0.1.md)、[T09検証記録](docs/verification-t09-2026-09-16.md)、[T10検証記録](docs/verification-t10-2026-09-16.md)、[T10法源確認](research/2026-09-16-criminal-procedure-t10-source-review.md)、従来の各仕様・検証記録、[本日の日誌](devlog/2026-09-16.md)から確認できる。

調査28項目・自前エンジンとLLMの計画・24課題台帳も保存済み。

## まだできていないこと

- 自然文からの自動形式化、LLM接続、一般の意味lint、JSON Schema規格のスキーマファイル、署名付きのreviewer認証。
- 手書き解釈IRはdecisionの小さな部分だけ。T07の刑法41条reviewも開発fixture作者によるPROVISIONALな記録である。別のT08カーネルは手書き規範だけを受け取り、義務・禁止・許可を原文package、candidate、review、scope expectationsから変換する経路はない。複数候補、部分source unitの独立レビュー、実法令の専門家レビューも未対応。
- e-Gov全文の全条項棚卸し、号・表・図・数式・引用構造を含む抽出profile、source unit間の改版対応。XML本文自身によるrevision IDの証明、署名・第三者timestamp。
- 規範の優先順位・例外、反復event、open-world観測、暦・休日・単位変換、一般の主体・対象、実際の違反・救済・権限・裁量、規範・手続モデルの改定差分。T09/T10は一回限りslotと有限候補時刻に限定する。
- 段階別診断は単純な原子整数比較以外の一般的な論理矛盾・範囲外理由、最小原因、修正案を判定しない。`expected_inactive`の正しさとT05 source/review chainは別のホストレビュー・checkerに依存する。
- T06測定CLIはreport出力pathと入力pathの同一性を拒否せず、長時間run中の入力変更をsnapshotまたは開始前後hashで排除しない。正式runは分離pathを使い、完了後のbinding一致を確認したが、実行中ずっと不変だったことまでは証明しない。report checkerは測定時hashを現在の同一source pathへ照合するため、後続の正当なsource変更でも歴史的reportがstaleになる。測定時source snapshotとcurrent-source状態の分離は未実装。
- 自前SATによる高速化、CNF変換、画面、カーネルの機械証明。
- [T12の容量対策](planning/t12-evidence-scaling.md)は設計済みだが未実装。境界値同値類、compact certificate、逐次証拠、確実な下限preflight、捕捉可能な想定外例外のexit 2は、旧全列挙との対照と独立checkerを通るまで現在の保証へ含めない。

今回の`finite-decisions/1`と手書き変換profileは将来計画の`finite-rules/1`の小さな部分。24課題がすべて解消したという意味ではない。原文・候補・review・Coreの対応と固定gold例は検査できるが、自然文との意味対応そのものは未検証。

現在の`finite-decisions/1`系の上限はモデル1 MiB・証拠8 MiB・全Cartesian積10,000状況。10,000は列挙のハード上限であり、処理可能件数の保証ではない。T06の固定100規則・10出力familyでは証拠8 MiBが先に効き、checkは5,661、diffは3,172、reachabilityは5,646、stagedは3,704が最後の成功だった。次の1 contextでは各経路が`LIMIT_REACHED`になった。同じ8,192状況でも静的matrixは密度とbackgroundにより23/32経路が完了、9/32が上限到達となった。この値は合成family固有で、一般上限ではない。

`finite-norms/1`にもモデル1 MiB・証拠8 MiB・状況10,000の上限があり、行動割当4,096、列挙前の状況×行動候補100,000組を追加上限とする。`finite-procedure-time/1`はモデル1 MiB・証拠8 MiB、slot 8、context 10,000、1 contextのtrace 4,096、context×trace 100,000を上限とする。T08〜T10の保存fixtureは性能上限を測ったものではない。

## 次の小さな一歩

[段階拡張計画](planning/legal-scale-roadmap.md)のT01〜T10とT03.1を、それぞれの限定profileで完成した。次はT11で、刑法43条・44条等から一つの狭い論点を選ぶ。先に裁量として許される選択肢、条件付き効果、各則参照、事実認定を入力前提にする範囲を仕様化し、単純なtrue/false衝突へ押し込まない。

T10は刑事訴訟法203条から205条の標準数値期限だけを扱う`manual_fixture_review`である。204条経路、55条の一般暦、56条・規則66条等の延長、206条の裁判官判断、個別事件は未解決のまま残す。将来revision `323AC0000000131_20270331_507AC0000000039`が施行されたらpackをstaleにし、source・coverage・review・bindingを再作成する。

[刑法41条T07](examples/interpretations/penal-code-41/README.md)と[T10刑事手続pack](examples/procedures/t10-criminal-procedure-203-205/README.md)はいずれも法律専門家未確認のPROVISIONALな開発fixtureである。[次段階への引継ぎ](planning/sol-handoff.md)はT11の論点選定と意味論設計用に更新した。

## 関連資料

- [開発日誌](devlog/README.md)
- [全体の計画](planning/README.md)
- [実装ロードマップ](planning/roadmap.md)
- [既知課題](planning/known-issues.md)
