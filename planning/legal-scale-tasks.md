# 段階拡張の作業チケット

2026-09-15作成・2026-09-16更新。**T01〜T08とT03.1は各限定profileの実装・独立検査・記録まで完了。次はT09。**
全体像は[拡張計画](legal-scale-roadmap.md)、着手用の依頼文は[引継ぎ](sol-handoff.md)。

完了の証拠と実測値は[T01〜T03検証記録](../docs/verification-t01-t03-2026-09-15.md)、[T04検証記録](../docs/verification-t04-2026-09-15.md)、[T05検証記録](../docs/verification-t05-2026-09-15.md)、[T03.1検証記録](../docs/verification-t03.1-2026-09-15.md)、[T06検証記録](../docs/verification-t06-2026-09-15.md)、[T07検証記録](../docs/verification-t07-2026-09-16.md)、[T08検証記録](../docs/verification-t08-2026-09-16.md)にまとめた。

## 順序

通常は T01 → T02 → T03 → T04 → T05 → T03.1 → T06 → T07 → T08 → T09 → T10 → T11。
T12/T13は必要性が生じたときに入れる。T06では証拠容量が先に制約になる固定例を得たため、T12は省サイズ証拠を優先候補にする。SAT化は探索時間の必要性を別に判断する。T14は各packの蓄積に合わせて少しずつ進める。T12/T13の完了を最初の刑法packの前提にしない。

| ID | 状態 | 作業 | 依存 | 主な成果物・完了条件 |
|---|---|---|---|---|
| T01 | 完了 | 20規則の教材 | 現行v0.1 | 既存6規則を残し、期待例つき20規則の問題版/修正版を検査 |
| T02 | 完了 | 改定差分 | T01 | 同じ入力に対する結論・衝突・gapの変化を独立に検査 |
| T03 | 完了 | 到達可能性の診断 | T01 | enabledになれない規則と、enabledでも常に抑止される規則を区別 |
| T04 | 完了 | 原文・公式法令の保存 | T01 | 固定版・元データ・抽出文・条項ID・hash・取得メタデータ |
| T05 | 完了 | 最小の手書き解釈IR | T04 | 原文→解釈→Core、参照lint、未解決の保持、変換来歴 |
| T03.1 | 完了 | 非到達理由とscope期待 | T03/T05 | 段階件数、期待内/意図的範囲外/未指定、独立証拠、終了コードを実装・検査 |
| T06 | 完了 | 50/100規則と計測 | T02/T03.1/T05 | 固定合成matrix・sentinel・4経路の容量境界・hash付きreportを保存 |
| T07 | 完了 | 刑法41条の最小pack | T04/T05/T03.1/T06 | 一方向の年齢条件、原文と期待例、未実装の認定・年齢計算を明示 |
| T08 | 完了 | 規範の最小意味論 | T05/T07 | 架空例で義務/禁止/許可、履行可能性と背景の区別 |
| T09 | 次 | イベント列・時間 | T08 | 小さな手続で期限・順序・観測打切り・境界を検査 |
| T10 | 未着手 | 刑訴法の最小pack | T04/T05/T09 | 55条・203〜206条周辺の採用部分と依存先を検査 |
| T11 | 未着手 | 刑法の次の論点 | T07/T08 | 43・44条等の候補を一つ選び、必要な裁量/参照の意味を追加 |
| T12 | 未着手 | 証拠付き高速化 | T06の測定で必要と判明 | 参照経路・意味・変換・証拠を維持して対象を拡張 |
| T13 | 未着手 | LLM候補支援 | T05/独立gold | 候補生成・意味lint・保留・修正・未見評価 |
| T14 | 未着手 | 章・法令横断と全体台帳 | 対象packの完了 | 全体の棚卸しと、実際に意味検査した範囲を区別 |

T09以降は一度で全部作る指示ではない。仕様・最小fixture・実装・独立checker・検証に小分けして、都度日誌を残す。

## T01: 最初に作る20規則（完了）

対象は星見クラブの拡張。区分別の参加条件、会費、割引、貸出上限など、現在のdecisionだけで表せる内容から20規則を設計する。締切や義務はまだ混ぜない。

作業:
1. AGENTS/STATUS/現行仕様/既存の検証記録を読む。
2. 既存unittestと6条のbroken/fixed CLIを再実行し、着手時の基準を記録。
3. 架空原文と採用する入力範囲、必要な出力を先に記述。1モデルの全積は10,000以下、証拠8 MiB以下。余裕のある小さい範囲を選ぶ。
4. 原文を読んで期待値を固定する。条件の重なり、required出力の抜け、発火しない例外、例外への例外、同値の帰結、未指定Boolを含める。
5. 別名の新教材を追加し、旧6条の教材をそのまま残す。問題を入れる場所を記録し、修正版で対応箇所が直ることを示す。
6. 自前analyze→verify、証拠保存→別コマンドverifyを通す。対応する意味テスト、結果の範囲、件数を記録。

予定の置き場所: examples/club20/ と tests/の専用テスト。goldは自動出力のコピーだけで作らず、原文から期待する具体例を書いた上で照合する。

完了条件: 旧fixtureが回帰せず、新しい20規則で意図した問題と修正が確認できる。問題版は終了コード1、修正版は採用照会で0、上限打切り等は2。証拠と説明の参照先が一致する。
今回の範囲外: IR全体、法令取り込み、LLM、SAT、Rust化、画面。

実績: 20規則・416状況。問題版は資格衝突32、料金gap32、貸出衝突4、修正版は全照会0。原文由来の全状況gold、保存証拠、専用14テストを追加した。

## T02: 改定差分の仕様から実装へ（完了）

最初は同じprofile・同じ入力領域・互換な出力型の2モデルだけを比較する。比較できない型/領域差は明示的に拒否してよい。領域が異なる場合を後から追加するなら、共通範囲と追加/削除範囲を別に報告し、共通部分の0件を全体同値とはしない。

各入力について、出力値の集合とdefined/absent/conflictingの状態を比較する。根拠IDだけの変更は説明の変化として分け、値が同じなら意味差としない。新たな衝突、解消した衝突、gapの発生/解消も表示する。

証拠は左右のモデルhash、比較profile、照会、scopeに結び付ける。両モデルがそれぞれ検査済みであるだけで比較集計まで正しいとしない。checker側で差分の件数・具体例・全範囲を独立に確認する。

完了条件: 閾値変更、例外の追加/削除、規則の名前/配列順だけの変更、比較不能な型、偽の差分集計、scope欠落のfixtureが期待どおり。新しい照会・証拠形式は版を定義し、古い証拠を黙って読み替えない。

実績: `finite-decisions-diff/1`と独立checkerを実装。問題版→修正版で意味変化68出力×状況、重複除外36状況を確認し、専用34テストを追加した。

## T03: 死んだ規則と例外で抑止される規則（完了）

enabled件数/effective件数を別に集計する。0件の意味を、背景が空な場合と区別する。常に抑止された規則を不要と断定して自動削除しない。例外がなくなると復活することを説明できるようにする。

完了条件: enabled=0、enabled>0かつeffective=0、一部effective、例外復活の対照例。集計改ざんはcheckerで拒否。正式queryに加える前に意味・結果・証拠の版を固定する。

実績: 4分類と独立checkerを実装。20規則の両版でR20だけが宣言範囲内の非到達、常時抑止0、一部抑止7、成立時常時有効12と確認し、専用20テストを追加した。

残る範囲: 旧reachability v0.1の`unreachable`は、宣言domain内でguardに成立例がない場合と、facts/背景で成立例が全て除外される場合を分けない。この互換経路は維持し、区別が必要な場合はT03.1で追加した段階別経路を使う。

## T04: 原文を固定する（完了）

最初は短い架空原文で、UTF-8原文、コードポイント範囲、改行/文字参照の抽出規約、原文単位manifestを実装する。その後、公式e-Govの必要な法令だけを取得する。XML原文と取得メタデータを保持し、取得時点と施行時点を混同しない。

対象のlaw_id/revision_id、URL、取得日時、元データhash、抽出文hash、抽出版を記録。附則・経過措置・準用・他法令・関連規則は参照台帳へ。未解決の参照は文字列のまま隠さずissueにする。

完了条件: 絵文字、結合文字、CRLF、同じ条文の反復、改正版差替え、引用欠落、API失敗のfixture。取得に失敗したとき古い本文を現行として使わない。offlineで保存原文を再利用できる。
参考: [今回確認した公式資料](../research/2026-09-15-legal-source-review.md)。

実績: [`rule-source-package/1`](../docs/source-package-v0.1.md)を実装。外部capture specを固定分母として、raw/metadata、取得記録、抽出text、revision-local source unit ID、完全な構造path、0-based半開codepoint spanをhash chainで束ね、producerをimportしないcheckerがrawから全単位をoffline再構成する。`xml-unit-text/2`で本文空白とRubyの境界を限定し、別に記録したbundle hashによる取得記録の不変性検査を追加した。生成はstaging検査後だけLinux filesystemのatomic no-replaceで新規directoryへ公開し、取得失敗と既存destinationを成功扱いしない。

[Unicode架空原文](../examples/sources/fictional-unicode/)3単位と、明示版の全文XML/metadataを持つ[刑法41条snapshot](../examples/sources/penal-code-41/)1単位を保存した。刑法XML内の本則/附則の同番号Articleは完全pathで区別し、法令同一性fieldも照合する。空白・Ruby、自己整合な取得記録改ざん、symlink、公開race、別版、引用欠落、不正UTF-8、CRLF、同文反復、取得二本目失敗、保存例回帰を含む35テストを追加し、全159テスト合格。正確なhashと残る範囲は[T04検証記録](../docs/verification-t04-2026-09-15.md)。

残る範囲: e-Gov抽出は本則の単純なArticleだけ。号・表・図・数式等は新profileが必要。今回の固定分母は選んだ41条1単位で、刑法全条の棚卸しではない。XML本文だけではrevision IDを証明できず、署名・第三者timestampも未実装。原文の意味解釈とCore接続はT05/T07へ送る。

## T05: LLMなしで最小IRを通す（完了）

[形式化計画](formalization.md)のうちdecision/condition/exception/reference/assumption/unresolvedから始める。権限・義務・時間のような未対応kindを勝手にdecisionへ変換しない。

candidateとホスト管理の記録を分離。source→IR→Coreノードへの来歴、manifest全単位との対応、未解決依存、意味lintを実装する。pack内で成立を期待する規則、意図的に範囲外へ残す規則、未指定を、source unitとscope hashに結び付けたホスト管理の期待として保持する。承認や範囲外を候補自身が自己申告するフィールドは拒否。

現在のCoreはauthored_core専用で未知キーを拒否する。実装時にwrapperとCoreの境界を設計し、原文/解釈/変換hashと検査証拠を結び付ける。単に原文キーを追加したり、authored_coreに「解釈確認済み」と表示したりしない。

完了条件: 否定逆転、必要/十分条件、ただし書欠落、参照漏れ、未承認候補、古い原文をfixtureで識別。機械検査と意味レビューの状態を分け、未解決の依存先から確定結果へ進めない。

実績: [`rule-interpretation-task/1`、candidate、review、scope expectations、生成package](../docs/interpretation-ir-v0.1.md)を別形式で実装した。十分条件の定数decisionと、同じ出力への明示的replacement exceptionだけを既存Coreへ決定的に変換し、producerをimportしないcheckerが原文manifestからCore、全provenance、review summary、host gold例、packageを再構成する。source bundle、review、scope expectationsの外部hashを生成時から必須とし、保存packageも外部hashを指定して再検査できる。

[架空会員規約の保存fixture](../examples/interpretations/member-eligibility/README.md)は2 source units、resolved reference 1件、2 Core rules、5 host gold例を持つ。104 Cartesian状況のうち背景制約後78状況を扱い、`LOWERING_VERIFIED`と`HOST_REVIEW_RECORDED`を別状態で記録する。candidateの承認・対象外自己申告、staleなreview、未採用assumption、必要条件、未解決参照、古いmanifest、引用・参照・Core・来歴・scope・package改ざん、否定/閾値/必要十分/例外の既知変異を拒否する。選択したsource unitは同じunitを起点にする全issue/referenceを継承し、未選択dummyへ未解決依存を逃がせない。

残る範囲: 保存reviewはCodexが作った開発fixtureで、ユーザーや法律専門家による承認ではない。一般の日本語意味lint、部分source unitの独立レビュー、LLM接続は未実装。T05の`finite-decisions/1`へのloweringは十分条件の定数decisionと明示的replacement exceptionだけで、義務・禁止・許可・期限を扱わない。T08は直接記述した時間なし規範を別profileで扱うが、原文・candidate・review・scope expectationsからそこへ変換する経路は未実装。T05のscope expectationsと段階別到達可能性の照合はT03.1で実装した。

## T03.1: 非到達理由とscope期待（完了）

2026-09-15の[Opus 5レビュー](../docs/review-notes-2026-09-15.md)を受けたT03の後続。[`finite-decisions-staged-reachability-certificate/1`](../docs/staged-reachability-v0.1.md)を別形式で追加し、旧reachability v0.1の証拠・CLI契約を維持した。

実績: 宣言Cartesian積を固定順で全数列挙し、各規則のguard成立`G`、guardとfacts成立`GF`、guardとconstraints成立`GC`、両filter後のenabled `E`、override後effective `V`の件数と最初のwitnessを証拠化した。facts/constraintsの4セル分割、空background、activation stage、常時抑止も別に記録する。producerをimportしないcheckerがモデルから完全なcanonical certificateを再構成し、行・順序・集計・witness・hash・期待の改ざんを拒否する。

`flag and not flag`と、age 0〜25に対する`age >= 26`は、どちらも現在の有限意味論ではguard成立0である。直接の整数比較から宣言範囲との非交差を確かめられる場合だけrange hintを付け、それ以外は`no_guard_witness_in_declared_domain`として残す。一般のBoolean ASTを「論理矛盾」と「宣言範囲外なら成立」へ完全分類したとは主張しない。

T05のホスト管理`rule-scope-expectations/1`は外部SHA-256を必須とし、Core model、source manifest、task/candidate/review/snapshot/scope、全Core rule IDへ結び付ける。`expected_in_scope`なのに非到達、未指定の非到達、常時抑止はattentionにし、明示的な`expected_inactive`と非到達が一致する場合だけ情報扱いにした。期待なしでattentionが残る検証済み証拠はexit 1、attentionなしは0、不正・不一致・空background・上限到達は2とした。

保存fixture: [星見クラブ原文pack](../examples/interpretations/handbook-scope/README.md)では52状況のR20を`expected_inactive`と照合しattention 0、期待を外すとattention、domainを26歳まで広げると最初のwitnessをcase 52として検出する。[架空会員規約](../examples/interpretations/member-eligibility/README.md)では104状況、背景適合78状況に対し、成人規則の一部抑止と停止規則の常時有効を照合してattention 0とした。両方のcertificateをrepositoryへ保存し、外部hash付きoffline検査を回帰に含めた。

完了条件として、guard成立0、単純な整数範囲非交差、facts除外、constraints除外、除外要因の重なり、enabled>0/effective=0、空background、期待の一致/不一致と各種改ざんを固定テストで区別した。[検証記録](../docs/verification-t03.1-2026-09-15.md)に実測と受入結果を残した。

残る範囲: `expected_inactive`はホストが有限scopeについて記録したレビュー判断であり、原文や法的解釈の正しさを証明しない。T03.1 checkerはT05のsource/task/candidate/review chainを再構築しないため、原文からの経路を主張する際はT05の`verify-interpretation`も併用する。完全性は宣言された固定有限Cartesian積の全数検査に限る。

## T06: 50→100規則、依存と計測（固定合成ベンチマーク完了）

最初のsliceでは、規則数、guard成立密度、background適合率、検査経路を分離して測るため、意味を持つ実領域packではなく固定合成`authored_core`を採用した。実際の申込・施設利用・料金等の複数領域、共有定義、参照グラフはL3の後続作業として残す。局所では無矛盾でもunionで衝突する例と、例外への例外による原則復活は独立sentinelへ固定した。

計測項目は実行規則数、変数/領域、全積、背景適合数、producer/checker別時間、`tracemalloc` peak、証拠bytes、打切り理由とした。`check`/`diff`/旧`reachability`/`reachability-staged`ごとに、最大成功context数と最小`LIMIT_REACHED` context数を分けた。規則数・出力数、ID/値の長さ、1状況で有効な規則数、背景適合率を固定し、generator/config/hashを保存した。原文単位数は0とせず、T04/T05由来でないため`null`とした。

2026-09-15の[Opus 5の掲示板報告](../docs/review-notes-2026-09-15.md)を受け、13変数・8,192状況・50/100規則・10出力の別の合成ベンチマークを再現可能な形で追加した。同じレビューで報告された差分の実効上限9,457/5,877/5,284/3,566は、元モデルが保存されておらずモデル内容にも依存するため、一般上限や今回の再現値には使っていない。モデル/生成器の版・hash・実行コマンド・環境、MB/MiBと正確なbytes、実測と推計の区別をreportへ保存した。乱数は使わない。

同じ全積でもguard 1/8・7/8とbackground 1・1/8を変えて測った。全8,192状況を採用する`100-dense-full`は4経路すべて証拠上限に達し、同じ100規則・denseでも1/8採用ではcheck/diff/reachabilityが完了した。backgroundで大半を除外しても現行の列挙予算が減ったとは扱わない。

完了結果: 局所2モデルは無矛盾、unionだけ1衝突となる人工例とoverride復活を固定した。静的32経路は23件が独立checkerまで`VERIFIED`、9件が証拠8 MiBで`LIMIT_REACHED`。固定100規則・10出力familyの連続境界はcheck 5,661/5,662、diff 3,172/3,173、reachability 5,646/5,647、staged 3,704/3,705だった。各組の前者が最後の成功、後者が最初の失敗。4失敗endpointの実CLIは新規certificateを残さず、既存targetも変えなかった。

正式reportのraw SHA-256は`6bda457de5e19dbcbd74bb7df50f528b1c4dd6ca1e1040a972af35c7d3af1068`、body SHA-256は`4c9478c881ec9ac15988a195e3309ba61652361131c087fbdf741c90e53dd7fe`。全数値、環境、source binding、endpoint hashは[T06検証記録](../docs/verification-t06-2026-09-15.md)にある。この結果はT04/T05に由来せず、自然文・法的正しさ・一般上限を証明しない。

保存report専用checkerは外部raw hashを必須とし、現在のsource/model、report構造・算術、密度、worker status、境界endpoint、report出力と入力pathの分離をproducer非依存で再検査した。正式reportはstatic 8、boundary 4、完了workflow 27、`LIMIT_REACHED` workflow 13として`VERIFIED`。性能値の再実測、環境の第三者証明、保存されていない静的certificate本体の再検査ではない。

残る制約: 測定CLIはreport出力と入力pathの同一性を強制せず、長時間run中の入力変更をsnapshotや開始前後hashで排除しない。正式runは分離pathを使い、完了後のbinding一致を確認した。将来の測定では新規の分離pathを使い、入力snapshotまたは前後hash gateを追加する。証拠bytesが先に制約となる固定例を得たため、T12では省サイズ証拠を優先候補にするが、小scopeのT07を妨げない。

## T07: 刑法41条の最小pack（限定profile完了）

保存済み刑法41条`ARTICLE_41`の1 source unitから、当該条文による十四歳未満の不処罰条件だけを、1十分条件・1 Core rule・1 optional出力へ手書きで変換した。[保存fixture](../examples/interpretations/penal-code-41/README.md)は13〜15歳、年齢status、行為時statusの12 Cartesian状況を持ち、facts/constraintsは空。13歳・両status establishedだけがdefined `true`となり、14歳以上や未知・行為時点未確定はabsentのまま残る。absentから処罰可能性、犯罪成立、責任又は有罪を導かない。

`verify-interpretation`は外部source/review/scope/package hashを使って`LOWERING_VERIFIED`、host gold 12を返した。`--json`結果は`manual_fixture_review`と`provisional: true`を明示する。別chainの`verify-reachability-staged`は全積12、guard/enabled/effective 1/1/1、scope期待一致、attention 0を返した。`lt`→`le`変異は14歳goldにより`SEMANTIC_MISMATCH`、同じ年齢入力への矛盾factsは`INPUT_INCONSISTENT`となる。[検証記録](../docs/verification-t07-2026-09-16.md)に全anchorと境界を固定した。

完了範囲は開発fixtureの手動解釈、Core変換、有限scope内の証拠検査まで。法律専門家レビュー、年齢計算、事実認定、他条・他法令、刑法全体の意味検査は未実装である。

## T08: 規範を小さな架空例で定義する（完了）

義務O、禁止F、明示的許可P、事実、決定、裁量/権限の未対応境界を仕様化する。有限状況cと、時間順序を持たない有限Boolean行動割当tauを分ける。背景だけでも行動不可能な場合を分離する。

完了条件: O(A or B), F(A), F(B)の三者で初めて履行不能になる例、一つの状況だけ履行不能な例、許可が行為の義務にならない例。存在/全称・量化の順序を固定し、各状況の行動候補をカーネルとcheckerで独立に確認する。時間なしの小さい段階から始める。

実績: 別profile`finite-norms/1`と独立CLIを実装した。[架空fixture](../examples/norms/t08-three-way/README.md)は8状況、admitted 4、各8行動候補で、対象外4、背景不能2、規範上の履行不能1、履行可能1を分ける。`P_C`はusable/nonexercise witnessを各1件持つ。三者の各規範を一つずつ外す対照、状況ごとの存在量化、複数許可、`F(A and B)`、改ざん・上限・atomic保存を38件の専用回帰で固定し、全suite 301件が合格した。[仕様](../docs/normative-kernel-v0.1.md)と[検証記録](../docs/verification-t08-2026-09-16.md)を保存した。原文/review chain、時間、優先関係、実法令は未対応。

## T09: 有限の手続・時間

架空の申請→受領→審査→決定→通知を5〜10規則から始める。主体、イベント、時刻、状態遷移、単位付き差分、観測終了、期限の包含境界を追加する。

完了条件: 起算イベント違い、同時刻、期限直前/一致/直後、部分的な禁止期間、観測未完了、禁止期間終了後に履行候補が再び現れる例を再現する。この候補復活は時間条件の終了として扱い、未定義の規範overrideを導入しない。少数候補時刻による検査と全時間の被覆を区別する。時間の意味論変更は別profileにする。

## T10: 刑事訴訟法の最小pack

55条・203〜206条周辺を入口として、依存する条文・規則・例外を調べる。初回は203条→205条経路の数値期限診断に範囲を絞る。55条全体の暦計算を初回で実装済みとしない。必要なら先に時間・暦の小さな仕様追加チケットへ分ける。

完了条件: 身体拘束と受領の異なる起算、送致の手続と受領の違い、期限境界、206条に関わる評価未確定、公訴提起/釈放、観測終了の違いの固定例。数値期限だけの結果を手続全体の法的判断へ昇格させない。次に204条経路を別packとして追加する。

## T11〜T14: 必要に応じた拡張

- **T11 刑法の次の論点**: 43・44条などを一つ選ぶ。裁量として許される選択肢、条件付きの必要な効果、各則参照を先に仕様化する。単なるtrue/falseの衝突にしない。評価概念そのものを判定しない場合は入力前提を記録する。
- **T12 証拠処理・高速化**: T06の計測をもとに、証拠bytesには独立再構成できる省サイズ表現、ピークメモリには逐次処理、探索時間には自前DPLL/CNF等を選ぶ。逐次化だけでは証拠容量や全積上限を解消しない。case列を省く場合は、長さ区切りとdomain separationを持つ全列commitment等をproducerが保存し、checkerが独自streamから再計算する。新形式ではモデル/queryへの結び付け、全範囲の被覆、欠落・重複・途中切断・偽集計の拒否をcheckerで確認する。変換や分割の検査が未実装なら探索結果を正式証拠へしない。旧参照経路と小さな全数問題・変異テストを維持する。
- **T13 LLM支援**: 少数の架空goldから候補生成と修正を試し、その後に限定法令packへ進む。原文をまたぐ未見評価、否定/例外/単位/参照の誤訳、全保留による偽の合格を検査。実装を進めるコーディングモデルの利用と、製品へのLLM接続は別。
- **T14 全体台帳**: 法令全体を条項単位で棚卸しし、formalized/partial/unresolved/out_of_scopeを固定分母で記録。章・他法令間の依存を追跡。新しい法令版で影響するpackとレビューをstaleにする。構造検査の完了と意味検査の完了を別々に報告する。

## 毎回の終了時

変えた意味と理由、実行コマンドと結果、証拠/原文へのリンク、未解決点、次のチケットを日誌とSTATUSへ反映する。期待値を結果に合わせて変更する場合は、原文や仕様の訂正理由を必ず残す。できていない機能を完了にしない。
