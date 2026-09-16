# 既知課題と受入条件

状態: **限定profileで一部の対策を実装・テスト済み。24課題全体は未完了。** 2026-09-16時点の対応と残る範囲は[基礎検証](../docs/verification-2026-09-15.md)、[T01〜T03検証](../docs/verification-t01-t03-2026-09-15.md)、[T04原文package検証](../docs/verification-t04-2026-09-15.md)、[T05手書き解釈IR契約](../docs/interpretation-ir-v0.1.md)、[T03.1段階別到達可能性仕様](../docs/staged-reachability-v0.1.md)と[検証記録](../docs/verification-t03.1-2026-09-15.md)、[T06合成ベンチマーク検証](../docs/verification-t06-2026-09-15.md)、[T07刑法41条pack検証](../docs/verification-t07-2026-09-16.md)、[T08有限規範仕様](../docs/normative-kernel-v0.1.md)と[検証記録](../docs/verification-t08-2026-09-16.md)、[T09有限手続・時間仕様](../docs/procedure-time-kernel-v0.1.md)と[検証記録](../docs/verification-t09-2026-09-16.md)、[T10検証記録](../docs/verification-t10-2026-09-16.md)にある。この台帳は全体計画の課題と合格条件を定める。

分類:

- **実装で排除**: 不正状態を受理しない、誤った結果を確定しないようにする。
- **意味を明示**: 複数ありうる意味論から採用するものを定め、その意味で検査する。
- **境界で管理**: 対応していない範囲を検知して、未確定として返す。
- **照合で管理**: 原文との対応をレビュー・事例・来歴で確認する。一般的な完全保証とはしない。

## 課題台帳

| ID | 問題 | 対策・分類 | 固定する反例と合格条件 | 主担当 / ゲート |
|---|---|---|---|---|
| K01 | 未知を偽として処理する | 補完状況集合で扱う。実装で排除 | 年齢不明で未成年を確定しない。真/偽の両補完を保存 | A/B / G1–G3 |
| K02 | 相反事実を後勝ちで上書きする | 根拠を別保持し入力不整合。実装で排除 | 同一事実の肯定/否定が両方ある場合、どちらかを採用しない | A/B / G1–G3 |
| K03 | 背景矛盾から何でも証明できる | 性質検査前に背景を確認。実装で排除 | age≥20かつage≤10で「問題なし」と返さない | A / G2–G3 |
| K04 | 義務と事実・違反を混同する | 型と検査を分離。意味を明示 | 提出義務＋未提出を規則矛盾とせず、履歴に応じ違反/未観測とする | A/B / G1–G3 |
| K05 | 明示許可を義務や禁止不在に変える | 許可を独立記録。意味を明示 | 許可だけでは行為を強制せず、明示overrideなしで禁止を消さない | A/B / G3 |
| K06 | 例外の優先を勝手に補う | 根拠付きの対象指定辺のみ。意味を明示 | 同順位競合が入力順に依存しない。不適用の例外は原則を消さない | A/B / G1–G3 |
| K07 | 例外への例外・部分例外の意味が曖昧 | 復活と分割を仕様化。意味を明示 | R3→R2→R1でR1が復活。点ごとの決定の部分例外を確認し、存在量化の義務を時点ごとの義務へ変えない | A/B / G3 |
| K08 | 否定・別名・例外経由の循環を見落とす | 全参照を検査しv1未対応へ。境界で管理 | A if not B、B if not A、および別名経由の循環を検出 | A/B / G1 |
| K09 | 全体が一度SATなら全条件で安全と思う | 検査命題と量化を明示。実装で排除 | 18歳以上可・20歳未満不可から18/19歳を検出 | A / G2–G3 |
| K10 | 全状況での履行可能性を一つのSATで判定する | 状況と行動列の量化を分ける。実装で排除 | c0だけ履行不能・c1は可能なモデルで、c1の例だけで合格させない | A / G3 |
| K11 | 3規則以上の組合せを見落とす | 同時履行条件を検査。実装で排除 | O(A∨B), F(A), F(B)の三者で履行不能、二者だけなら可能 | A / G3 |
| K12 | 期間が重なれば必ず矛盾とする | 時間窓を量化し履行例を探す。意味を明示 | 1〜10日の提出義務、1〜5日の提出禁止は6〜10日で履行可能 | A / G3 |
| K13 | 期限外・観測不足を合格/違反に決める | 検査範囲と観測範囲を別表示。境界で管理 | 観測終了が期限前なら未履行を確定違反にしない | A/B / G3 |
| K14 | 数値の桁あふれ・単位・境界の誤り | 厳密型と検査付き演算。実装で排除 | 上限＋1、円/日、≤と<、暦境界を黙って変換しない | A/B / G1–G3 |
| K15 | 適用漏れ・死んだ規則・空の対象を混同する | totality宣言、段階別到達性、scope期待を分離。意味を明示 | 未定義を許したキーには漏れエラーを出さない。guard成立0、baseによる除外、常時抑止、空背景、意図的範囲外を区別 | A/B / G1–G3 |
| K16 | 自作探索器の枝抜けを信じる | 反例再評価と完全被覆証拠。実装で排除 | 片枝を落としたUNSAT証拠を拒否。小規模全数問題で列挙器と一致 | A / G2–G5 |
| K17 | CNF証拠が正しければ元Coreも正しいと思う | 変換検査を別ゲートにする。実装で排除 | compilerの≤→<変異を、CNF証拠が正しくても通過させない | A / G5 |
| K18 | checkerが本体と同じバグを持つ | 単純仕様・別実装・否定試験・証明義務。境界も明示 | 証拠改ざんを拒否。探索/最適化コードをcheckerへ流用しない | A / G2–G5 |
| K19 | 打切り・版違い・古い証拠を受理する | 全段階の上限と入力束を固定。実装で排除 | 旧IRの証拠、未知版、打切りcheckerを成功にしない | A/B / G1–G6 |
| K20 | coreを最少の原因や修正箇所と呼ぶ | 極小性と由来を限定。意味を明示 | 固定背景で要素除去後のSAT例を確認。原文削除の効果は再計算 | A / G3・拡張 |
| K21 | 型が合うLLM誤訳を正しいと扱う | 原文照合と独立事例。照合で管理 | 「18歳以下」→age<18という型正しい誤訳を18歳の例で検出 | B / G4 |
| K22 | 例外、曖昧語、外部参照を捏造/省略する | issue/assumptionと依存ゲート。照合で管理 | 「別に定める」「相当」を勝手に閾値化せず保留 | B / G1–G4 |
| K23 | 原文位置・版・引用がずれる | コードポイント位置、原文固定、変換来歴。実装で排除 | 絵文字、結合文字、CRLF、同文反復、改正差替えの全fixtureに合格 | B / G1 |
| K24 | 網羅率やLLM同士の一致で意味保存を保証する | 指標を分け、独立goldを保持。照合で管理 | 全件対象外・全件保留で合格不可。共通誤訳でも独立境界例で検出 | B / G4–G6 |

各課題には、今後 `fixtures/Kxx/`を作り、正常例・反例・期待するstatus・関係する規範ID・実装箇所を登録する。上表のすべてを実装で完全解消できると主張するのではなく、分類に応じた扱いと合格条件を満たす。

### K21〜K24のT05現在地

T05では、原文package、非信頼candidate、ホストtask・review・scope expectations、生成Coreと来歴を別入力にした。否定、18歳境界、必要条件と十分条件、replacement exceptionの既知変異をhost gold例で検出し、未解決reference/issue、未採用assumption、候補自身の承認・対象外申告、stale hashを変換gateで拒否する。選択したsource unitから未解決依存を未選択dummyへ移して隠すこともできない。

これはK21〜K24の限定fixtureに対する対策であり、一般の日本語意味保存を機械判定したものではない。保存reviewはCodexが作った開発fixtureで、人や法律専門家の承認ではない。LLM候補生成、未見文書での評価、100%保留を含む指標評価はT13まで未実装のため、K21・K22・K24全体は完了扱いにしない。

### K15の現在地と残る範囲

T03でrequired gap、`enabled=0`、`enabled>0/effective=0`、一部抑止、空backgroundを区別した。T03.1では別形式の段階別certificateを追加し、宣言Cartesian積におけるguard、facts、constraints、enabled、override後effectiveの件数とwitness、facts/constraintsの4セル分割を独立checkerで再構成する。これにより、旧reachability v0.1が`unreachable`へまとめる除外段階を限定profile内で観察できる。

T05のホスト管理scope expectationsは外部hashと全Core rule IDを検査し、T03.1が段階別結果と照合する。`expected_in_scope`の非到達、期待未指定の非到達、常時抑止はattention、`expected_inactive`と非到達の一致は情報として区別した。保存した2 fixture、stale/別rule/改ざんの負例、旧経路の回帰が合格したため、この限定対策を`tested`とする。

残る範囲: `expected_inactive`はホストによる固定有限scopeのレビュー判断で、法的正しさの証明ではない。直接の整数比較で範囲非交差を示せる場合以外、guard成立0の一般式を論理矛盾と範囲不足へ完全分類しない。T03.1単体はT05の原文・候補・review chainを再検査しないため、原文対応を伴う結果ではT05 checkerも併用する。旧reachability v0.1の形式と終了コードは互換性のため維持する。

### T06測定器の現在地と残る範囲

T06ではK16・K18・K19に関係する限定fixtureを追加した。50/100規則の決定的生成物、4つの証拠経路、局所/union衝突、override復活、最後の成功と最初の`LIMIT_REACHED`を固定し、成功certificateをoperation固有の独立checkerへ渡した。4つの上限到達endpointはexit 2となり、新規certificateを残さず既存targetを変更しなかった。これは固定合成workloadについての`tested`であり、24課題全体の完了ではない。

レビューで次の二点が残った。

- **output-input path guard**: `measure run --output`がconfig、manifest、generated model、generator、kernel source等の入力pathと同一でないことを明示検査しない。既定の分離pathでは発生しないが、入力pathと`--overwrite`を同時指定すると測定後に入力をreportで置換し得る。保存report専用checkerはrecorded outputと現在の入力pathの分離を拒否条件にしたが、測定CLIによる置換を実行前に防ぐものではない。修正までは既存入力と異なる新規出力だけを許す運用にする。受入条件は、全input bindingと同一path・そのsymlink/aliasをCLIが実行前に拒否し、入力bytesを変えないこと。
- **長時間run中のbinding race**: 測定開始時に固定生成物を検査する一方、source bindingは終盤のfile bytesから作る。実行中にconfig、manifest、generated model、generator、kernel sourceが変わると、workerが読んだ版とreportが結ぶ終端版の不一致をreport単体では排除できない。保存report専用checkerは現在のsource/modelとの一致を再検査するが、過去のrun中の不変性は復元できない。今回の完了後照合では16 bindingと10 endpointが現物一致したが、実行中ずっと不変だったことの証明ではない。受入条件は、immutable snapshot上で全workerを実行するか、全入力の開始前後hashを比較し、不一致ならreportとendpointを正式公開しないこと。
- **歴史的reportと現在sourceの混同**: 保存report checkerは測定時に記録したsource hashをrepoの現在の同一pathへ照合する。このため、測定後の正当なkernel変更でも過去reportの測定内容が壊れていないのに`source binding`はstaleとなる。T07では人向けCLI表示を変える案がT06正式reportの`rulekernel/__main__.py` bindingを失効させたため、その表示変更を戻し、T06 binding外の`interpretation_checker.py`が返すJSONの`review_method` / `provisional`だけを追加した。過去reportを書き換えて現実装に合わせてはいない。受入条件は、測定時sourceのimmutable snapshot又はcontent-addressed bundleをreportと共に保存し、歴史的測定束の再検査成功と、現在sourceが同じかという状態を別々に返すこと。

T06の容量境界は100常時成立規則・10 Bool出力というfamily固有である。自然文、T04/T05 chain、法的正しさ、一般の処理上限を検査しない。証拠bytesが10,000 contextより先に制約となる固定例を得たため、T12では独立再構成、全範囲被覆、欠落・重複・途中切断・偽集計拒否を維持する省サイズ表現を優先候補とする。

### K03・K05・K10・K11・K16・K18・K19のT08現在地

T08では、時間なしの`finite-norms/1`を既存decisionとは別profileで実装した。
対象状況ごとに全Boolean行動候補を列挙し、対象外、背景だけの行動不能、義務・禁止の
履行不能、履行可能を分ける。`O(A or B)`、`F(A)`、`F(B)`の
三者が揃った場合だけ不能になる対照と、状況ごとに別の候補を選ぶ量化順を固定した。
明示的許可はhard normへ入れず、許可ごとにusable/nonexercise候補を別々に数える。
同一状況の複数の利用不能許可は、permission×context組数と一意なcontext数へ分ける。

producerをimportしないcheckerが全context、全admitted trace、式、分類、permission、
witness、集計を再構成する。上限・空background・外部hash・model差替え・証拠改ざん・
producer変異・保存競合の負例を通したため、上記課題の時間なし有限fixtureに対する対策を
`tested`とする。

残る範囲: T08は人が直接書く`authored_normative_core`だけで、T05のsource、
candidate、review、scope expectationsへ結ばれていない。permissionは禁止を解除せず、
優先関係・例外・権限・裁量を扱わない。主体、対象、行動順序、時間、期限、観測終了、
実際の履行・違反・救済も未実装である。checkerとproducerはmodel validator、
canonical JSON/hash、Python処理系、標準ライブラリ、仕様理解を共有し、機械証明済みではない。

### K04・K12〜K14・K16・K18・K19のT09/T10現在地

T09では、有限event slot、排他的観測終了、包含期限、部分禁止を別profileへ実装した。期限前・期限座標・期限後、同tickのphase差、起算点欠落、時刻未確定、背景不能、規範不能を別statusにした。部分禁止の終了後に遵守候補が残る例、branch欠落・複製・順序・集計・witness・境界比較変異、上限とatomic保存をproducer非依存checkerで固定した。これによりK04、K12〜K14、K16、K18、K19の有限fixture部分を`tested`とする。

T10では、203条の48時間と205条の24/72時間を別normにし、送致と受領、代替行為、release triggerとrelease観測、数値超過と206条評価未確定を分けた。法源5単位、全文quote、coverage、暫定review、model、certificateの改ざんに加え、受領起点の誤置換、期限片方の削除、206条自動延長の変異を拒否した。

残る範囲: 候補外の連続時間、反復event、open-world観測、一般暦・休日・単位変換、期間延長、優先関係、救済、権限・裁量は未対応である。T10の意味対応は開発fixture作者の手作業reviewで、法律専門家の確認やsemantic loweringの証明ではない。checkerとproducerはvalidator、canonical JSON/hash、Python処理系、仕様理解を共有し、機械証明済みではない。公開checker/CLIは不正入力を構造化拒否するが、内部のbinding producer直接APIは完全なschema validatorではなく、構造不正の直接呼出しで`KeyError`になり得る。

## 完了を判定する記録

```text
issue_id
classification
status: planned | specified | implemented | tested | reopened
spec_version
positive_fixtures[]
negative_fixtures[]
verification_command
last_result
remaining_limits
proof_obligation_ids[]
review_record
```

テストに合格した `tested`も、「この問題が任意の入力で永久に起きない」という意味ではない。新たな失敗例が出たら `reopened`へ戻す。

## v1で受理しない構成

- 無限集合・無制限の時点・自由変数。
- 再帰的な規範、非層化の否定、規範から条件への参照。
- overrideの循環、意味保存を定義できていない時間窓義務の部分期間override。
- 意味未確定の裁量概念、解決していない参照や法令版。
- 必要な期限や演算が宣言範囲の外にあるモデル。
- 型が違う単位の暗黙変換、丸めが未定義の計算。
- 任意コードを含むLLM出力。

これらは「原文が誤っている」ではなく、`MODEL_INCOMPLETE`または`UNSUPPORTED`として区別する。

## 保証の受入文

正式な結果として出す文は、次の形に限定する。

> 指定された原文版と解釈、整合する入力条件、finite-rules/1の意味論、宣言した有限対象・数値・時点の下で、この検査命題について、確認済みの具体例がある／範囲内に例がない証拠を確認した。

自然文そのものの無謬性、法的解釈の唯一性、無制限の完全性、checkerと実行環境の無欠陥は含めない。これらの区別を結果データと画面の両方で保持する。
