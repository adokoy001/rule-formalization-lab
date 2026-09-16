# T12 証拠容量・ピークメモリ対策

2026-09-16設計、同日基礎実装。**`finite-decisions/1` の基礎 `check` に境界セルとcompact JSON Linesを追加した。T12全体は継続中で、上限値、旧証拠形式、diff/reachability、norm/procedureの証拠形式は変更していない。**

## 1. 結論

現在の8 MiB証拠上限に対して、次の四つを別の問題として扱う。

1. **失敗の扱い**: 公開CLIで捕捉できた想定外例外を未確定の内部エラーとしてexit 2にし、部分証拠を公開しない。
2. **実行前の見積り**: 確実な下限が上限を超える場合だけ早期停止し、経験的な予測値は参考情報にとどめる。
3. **証拠の省サイズ化**: 整数境界から意味が同じ状況クラスを導き、各クラスの代表値と重みを証拠にする。
4. **ピークメモリの抑制**: 証拠を逐次生成・逐次検査する。JSON Lines化だけでは証拠bytesや探索時間は減らない。

探索時間が実際の制約になった後に、自前CNF変換とDPLLを別段階で検討する。外部SAT/SMTを正式な検証経路へ直結しない。

## 2. 現在わかっている上限

`finite-decisions/1`はCartesian積10,000状況、証拠8 MiBを上限とする。T06の固定100規則・10出力familyでは、check 5,661、diff 3,172、reachability 5,646、staged reachability 3,704 contextが最後の成功で、それぞれ次の1 contextが証拠上限へ達した。この値は固定family固有であり、一般の処理可能件数ではない。

現在のdecision、norm、procedure producerとcheckerは、基本的にcaseまたはtraceの配列全体をメモリへ構築する。decisionとnormには生成途中の証拠bytes検査があるが、procedure producerは完成後の全体bytes検査である。逐次化にはピークメモリを下げる価値がある一方、同じ全caseを出力する限り8 MiB上限は変わらない。

初期実装では、元の具体状況10,000と証拠8 MiBのhard capを維持する。class数だけを数えて大きな元領域を受け入れず、producerとcheckerの実測を得た後にconcrete cardinality、class数、証拠bytesの上限を別々に再検討する。境界値同値類の初版は`finite-decisions/1`系だけを対象にする。normの行動候補とprocedureの明示event traceは同じ区間分割ではまとめず、逐次処理と失敗・上限契約だけを共有する。

## 3. 境界値による同値類

### 3.1 採用条件

初版では、整数変数がfacts、constraints、全rule guardの中で**整数定数との比較にだけ**現れるモデルを対象とする。diffでは左右両モデルの原子比較を合わせて分割する。BooleanとEnumは従来どおり全値を列挙する。

整数領域内で、全原子比較の真理値が変わる位置にcutを置く。

| 原子比較 | `x`側のcut |
|---|---|
| `x < c`、`x >= c` | `c` |
| `x <= c`、`x > c` | `c + 1` |
| `x == c`、`x != c` | `c`と`c + 1` |
| fact `x = c` | `c`と`c + 1` |

定数が左辺の場合は同値な向きへ直して扱い、cutは宣言領域へ切り詰める。このため「定数が8個なら常に8区間」ではない。比較演算子、等値比較、領域端によってクラス数は変わる。`INT_MAX + 1`のような領域外値をモデル整数として生成せず、domain端と内部cutを別に表現する。

現行文法は整数変数同士の比較も許す。`x < y`の真理値は独立した二つの長方形区間内でも変わり得るため、初版は該当モデルを圧縮対象外として全列挙へ戻す。算術、剰余、単位変換、暦、連続時間を将来追加した場合も、意味保存を別途証明するまで同じ扱いにする。

### 3.2 証拠に必要な情報

各クラスは少なくとも次を持つ。

- 各整数変数の閉区間、canonicalな最小代表値、元状況数を示す重み。
- Boolean/Enum割当と、元Cartesian順での先頭index。
- admitted、enabled、effective、診断結果。
- 集計へ加える重みと、元の具体値で表示するwitness。

多次元クラスは軸ごとの区間の直積であり、元の列挙順で一つの連続範囲になるとは限らない。`start + length`へ畳まず、軸範囲、重み、最小indexを別々に扱う。

checkerはproducerのpartitionを信用せず、モデル構文からcutを再導出し、クラスが宣言領域を重複なく完全被覆すること、代表値と重みが正しいこと、各関連原子の真理値がクラス内で一定であることを独立に確認する。欠落、重複、誤った重み、最大値側の取りこぼし、左右モデル片側の境界だけを使うdiffを拒否する。

現行certificateは各具体入力をcaseとして保存するため、代表値への置換は互換変更ではない。旧形式を残し、別versionのcompact certificateとして導入する。

### 3.3 現行fixtureでの設計用試算

画像内の「2,880状況から288クラス」という元モデルと保存証拠は、このrepositoryには存在しないため再現済み実績には数えない。

代わりに20規則の既存fixtureを一時的に構文解析し、age以外の4 Boolを全列挙したまま、整数比較の真理値ベクトルが等しい連続ageをまとめた。

| fixture | 元状況 | ageクラス | 圧縮後の組数 | case内の分裂 |
|---|---:|---|---:|---:|
| broken | 416 | `0..15`, `16..17`, `18..19`, `20..24`, `25` | 80 | 0 |
| fixed | 416 | `0..15`, `16..17`, `18..24`, `25` | 64 | 0 |

この試算後にcompact producerと独立checkerを実装し、旧全数経路との全照会対照を行った。問題版は80セル・35,360 bytes、修正版は64セル・28,309 bytesとなり、旧全数証拠と同じ照会件数・witnessを返した。保存hash、実行コマンド、負例は[検証記録](../docs/verification-t12-2026-09-16.md)に分ける。

T06の13 Bool静的matrixは整数軸を持たないため、この方法では8,192クラスのままである。整数`case_id`だけを持ち規則が常時成立する境界familyは意味上1クラスにできるが、旧T06は1 contextずつの証拠容量を測るfixtureなので、新形式の値で旧境界を置き換えない。T12の別benchmarkとして比較する。

## 4. 実行前見積り

`context数 × rule数`だけでは、rule IDや値の長さ、発火密度、背景適合率、query種別、trace形状が証拠bytesへ与える差を表せない。経験係数による予測超過をhard failureにすると、実際には収まる入力を拒否し得る。

初版は次の三段構えにする。

1. 既存のCartesian context、行動候補、trace組数の厳密な事前上限検査を維持する。
2. canonical JSONの固定部分と最低record形状から、証明できる下限が8 MiBを超える場合だけ列挙前に`LIMIT_REACHED`とする。経験的な中央値や上限予測は`advisory_estimate`として表示し、成功保証にも拒否理由にも使わない。
3. 生成中は1 record追加前に正確な累積bytesを検査する。procedure経路にもこの検査を追加し、完成後まで大きな配列を保持しない。

見積りには計算根拠、対象profile、context/trace数、下限・参考予測・hard capを別fieldで示す。整数桁あふれや見積り自身の過大な計算も上限エラーにする。

## 5. 逐次証拠

新形式は、1行1 canonical JSON recordの別certificate format/versionとする。少なくとも次の三種を順に置く。

1. **header**: format、profile、semantics、model/query hash、上限、canonical順、予定record数または総重み。
2. **case/class**: 連番、入力又はクラス、重み、結果。1 recordの最大bytesも制限する。
3. **trailer**: record数、総重み、全集計、witness、逐次commitment。

逐次commitmentは、domain tag、record index、長さ、canonical record bytes、直前hashを長さ区切りでhashする。hash対象はheaderと全case/class recordまでとし、commitmentを格納するtrailer自身は含めない。具体caseを省くcompact形式では、クラスrecord列のcommitmentに加えて、元の全具体行を仮想的に展開した列の別commitmentも保持し、producerとcheckerがそれぞれ逐次再計算する。checkerは期待する全recordを独自に同じ順で生成し、一行ずつ比較する。途中切断、空行、CRLF、重複key、不正UTF-8、欠落、複製、並替え、余分な末尾、偽集計、偽commitmentを拒否する。

producerは同一filesystemの一時fileへ書き、flush/fsync後にcheckerで最後まで検査し、atomic no-replaceで初めて公開する。失敗時は一時fileを除去し、既存の証拠を変更しない。外部のexpected certificate hashによるanchorも維持する。

逐次形式を先に全caseで実装すればピークメモリを測れる。境界値クラスを組み合わせた後に証拠bytesも減る。どちらか一方の効果を両方の改善として報告しない。

## 6. CLIの想定外例外

現在の主なCLIは`KernelError`と`OSError`を処理するが、`RuntimeError`や`TypeError`等の想定外例外は通常tracebackとexit 1になる。公開CLI境界では`Exception`を捕捉し、応答を構築できる場合は`INTERNAL_ERROR`、結果未確定、exit 2を返す。`KeyboardInterrupt`や`SystemExit`等の`BaseException`は捕捉しない。通常出力へtracebackや入力内容を混ぜず、明示的なdebug時だけstderrへ診断を出す。

`MemoryError`の応答はbest effortであり、エラーJSON用のメモリも確保できない場合やOSによるprocess終了はexit 2契約の対象にできない。成果物の保護は例外応答に依存させず、一時fileとatomic publicationで保証する。

ただし、T06正式reportは`rulekernel/__main__.py`や測定sourceのhashを現在のfileへ照合する。それらを直ちに編集すると歴史的reportがstaleになる。まず測定時source snapshotとcurrent sourceを分離するか、新baselineを保存してからdecision/T06 CLIへ適用する。norm、procedureだけを先行変更した場合も、全CLIで完了したとは表示しない。

## 7. 実装順と受入条件

1. **T12.0 契約とbaseline**: 旧certificateを維持し、T06 source bindingの移行方法、compact/stream version、エラー契約を固定する。
2. **T12.1 失敗と上限**: 捕捉可能な想定外例外のexit 2、資源枯渇時にも部分成果物を出さないatomic publication、確実な下限preflight、全producerの追加前bytes検査を負例で固定する。
3. **T12.2 class planner**: cut導出、代表値、重み、元indexを実装し、小空間では必ず旧全列挙と照合する。変数間比較は安全側にfallbackする。
4. **T12.3 compact certificate**: producer非依存checkerがpartition、完全被覆、重み、集計、witnessを再構成する。club20の旧/新結果を照合する。
5. **T12.4 streaming**: strict JSON Lines、逐次commitment、逐次checker、途中切断・並替え・複製等の変異テスト、atomic publicationを実装する。
6. **T12.5 再測定**: 旧T06 familyに加え、整数境界、等値、領域外定数、複数整数、diff両側境界を含む新familyで、時間、Python peak allocation、証拠bytes、checker時間を測り、concrete cardinality、class数、証拠bytesの上限を分ける必要があるか判断する。
7. **T12.6 探索時間**: 測定で必要なら自前CNF/DPLLへ進み、全列挙できる小空間で変換と結果を独立対照する。

完了条件は、旧形式の回帰、全数対照、独立checker、改ざん拒否、失敗時の非公開、測定値をすべて満たすこと。代表点で同じ結果が出た例だけでは、全域の検証完了としない。

## 8. 2026-09-16時点の実装範囲

- **T12.0 一部完了**: 旧 `finite-decisions-certificate/1` と歴史的T06 reportを維持し、別形式 `finite-decisions-compact-jsonl/1` を追加した。既存 `rulekernel` CLIのsource binding移行と想定外例外契約は未実施。
- **T12.1 一部完了**: compact CLIに捕捉可能な想定外例外のexit 2、同一directoryの一時file、生成後の独立検査、既存pathを置換しないatomic publication、保証下限preflight、record追加前の正確なbytes検査を実装した。norm/procedureに証拠圧縮は入れていない。
- **T12.2 基礎checkで完了**: 定数比較とfactsからcut、代表値、重み、元indexを導出し、整数変数間比較は全整数軸の単一値セルへfallbackする。小空間で旧全列挙と対照した。
- **T12.3 基礎checkで完了**: producerから独立したcheckerがpartition、cell、重み、集計、witness、具体case列を再構成する。club20の保存証拠で旧結果との一致を確認した。
- **T12.4 基礎checkで完了**: strict JSON Lines、二つの逐次commitment、逐次checker、構造・encoding・commitment変異の拒否、atomic publicationを実装した。virtual commitmentのため全具体状況の逐次再評価は残る。
- **T12.5 未完了**: club20とT06境界入力1件の実測は保存したが、整数境界、等値、領域外定数、複数整数を組み合わせた反復benchmarkとPython peak allocationの正式な再測定は未実施。
- **T12.6 未着手**: SAT化、CNF変換、自前DPLLは実装していない。探索時間が実測上の制約になってから判断する。

実装仕様は[compact証拠 v0.1](../docs/compact-certificate-v0.1.md)を参照する。現在も具体状況10,000、証拠8 MiBのhard capを維持する。`diff`、`reachability`、norm、procedureの圧縮は保証範囲に含めない。
