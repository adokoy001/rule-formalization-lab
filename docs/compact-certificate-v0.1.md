# compact decision証拠 v0.1

2026-09-16。`finite-decisions/1` の基礎 `check` を対象に、整数境界で意味が変わらない入力をセルへまとめ、証拠を strict JSON Lines で逐次処理するための実装契約。

形式名は `finite-decisions-compact-jsonl/1`、意味論名は `finite-decisions-boundary-cells/1`、partition形式は `finite-decisions-boundary-partition/1`。既存の `finite-decisions-certificate/1` を置き換えず、`compactkernel` の別CLIとして提供する。

## 対象と保証範囲

対象は手書き `authored_core` の有限decisionモデルに対する、結論の衝突と `required` 出力のgap検査である。モデルの意味論、入力順、override、照会順は[自前カーネル v0.1](kernel-v0.1.md)を引き継ぐ。

次はこの形式の対象外である。

- `diff`、`reachability`、段階別到達可能性。
- normとprocedureの証拠圧縮。
- 自然文からの自動形式化と、原文との意味一致の証明。
- 算術、単位、暦、連続時間、量化、SAT/SMT、CNF/DPLL。

具体入力のCartesian積は圧縮後のセル数とは別に数え、従来どおり10,000状況を上限とする。証拠ファイルも従来どおり8,388,608 bytesを上限とする。圧縮率だけを根拠に、これらの上限を超えたモデルは受理しない。

## 境界セル

整数入力がfacts、constraints、rule guardで整数定数との比較にだけ現れる場合、原子比較の真理値が変わる位置をcutにする。

| 比較 | セルの開始点として加えるcut |
|---|---|
| `x < c`、`x >= c` | `c` |
| `x <= c`、`x > c` | `c + 1` |
| `x == c`、`x != c` | `c`、`c + 1` |
| fact `x = c` | `c`、`c + 1` |

定数が左辺なら比較方向を反転して同じ規則を使う。宣言領域外のcutは捨て、符号付き64 bit最大値の次の整数は生成しない。Boolは `false, true`、Enumは宣言順の各値を一つずつのセルにする。

各セルは軸ごとの閉区間又は単一値、最小の代表値、元のCartesian積に含む具体状況数 `weight`、元の列挙順で最初の `first_case_index` を持つ。全原子比較の値がセル内で一定なら、enabled規則、override後のeffective規則、conflict/gapも一定になる。この条件の下で、セル1件の結果を `weight` 件として集計する。

整数変数同士の比較が一つでもある場合、現在のplannerは全整数軸を単一値セルへ戻し、`fallback_reason` を `integer-variable-comparison` にする。この場合も検査はできるが、整数軸は圧縮されない。

## JSON Linesの構造

証拠は次の順に並ぶ。

1. header 1行。
2. `cell_index` 順のcellを `cell_count` 行。
3. trailer 1行。

headerは形式・意味論・engine version、canonical model hash、入力順、全軸セル、具体状況数、セル数、圧縮有無、fallback理由、commitment方式を固定する。

cellは `cell_index`、軸範囲、代表入力、`weight`、`first_case_index`、`admitted`、`enabled`、`effective` を持つ。背景条件で排除されたセルも保存し、その場合の `enabled` と `effective` は空配列にする。

trailerはcell数、具体状況数、背景適合状況数、重み付きの全照会結果、最初の具体witness、class record commitment、virtual case commitmentを持つ。

各行は `sort_keys=True`、余分な空白なし、UTF-8のcanonical JSONとし、末尾をLF 1 byteで終える。checkerはCR、空行、末尾LFなし、重複key、NaN/Infinity、不正UTF-8、非canonical JSON、欠落・複製・並替え・余分な末尾を拒否する。

## commitmentと外部anchor

`sha256-chain/1` はdomainを分けた連鎖hashである。payloadは末尾LFを含まないcanonical record bytesとする。

```text
state_0     = SHA256(domain || 0x00 || "start")
state_{i+1} = SHA256(domain || 0x00 || "record"
                     || uint64be(i) || uint64be(len(payload))
                     || state_i || payload)
```

class commitmentはheaderをindex 0、cellを `cell_index + 1` として連鎖し、自己参照を避けるためtrailerを含めない。virtual case commitmentは旧形式と同じ具体caseを保存せずに全具体入力について再評価し、case index順に別domainで連鎖する。producerとcheckerはそれぞれ独立に計算する。

CLIの `--expected-certificate-sha256` は、headerからtrailerまでLFを含むファイル全bytesのSHA-256を照合する。commitmentとfile hashは改変検出に使えるが、署名や配布元の真正性を単独で証明しない。期待hashを別経路で固定して初めて外部anchorになる。

## producerとchecker

producerは境界セルごとに意味を評価し、record追加前に正確な累積bytesが8 MiB以内か確認しながら書く。生成前の `estimate` は、構文から計算できる最小record形状を合計した保証下限を返す。この下限が8 MiBを超える場合だけ意味評価前に停止する。下限が上限内でも、実際の発火規則やwitnessが増えれば完成証拠が収まるとは限らない。

checkerはcompact producer、既存の全数engine、共通partition plannerをimportせず、partition、式評価、override解決、照会集計、全具体case列を独自に再構成する。重み付きセルの集計とwitnessを、全具体caseから求めた集計とwitnessにも一致させるため、producerとcheckerのcut導出が同時に同じ誤りを持つ変異もこの照合で拒否する。共有するのは有限モデルvalidator、canonical JSON、モデルhash、上限定数等である。したがって共通validator、仕様、Python・標準ライブラリ・実行環境の誤りは信頼対象として残る。健全性の機械証明は行っていない。

証拠recordは逐次読書きし、全cell配列や証拠全bytesを同時に保持しない。一方、header内の軸表とモデルはメモリ上にあり、virtual case commitmentのため全具体入力を逐次再評価する。証拠容量とcell評価数は減り得るが、実行時間を具体状況数から独立にはしないし、Python heapの厳密な上限も保証しない。

CLIの `check` は出力先と同じdirectoryの一時fileへ書き、flush/fsync後に独立checkerで最後まで検査し、既存pathを置換しないhard linkで公開する。失敗時は一時fileを除去し、既存pathを変更しない。捕捉可能な想定外 `Exception` は `INTERNAL_ERROR`、結果未確定、exit 2とする。`MemoryError` の応答はbest effortであり、OSによるprocess終了まで保証しない。

## CLI

```bash
python3 -m compactkernel estimate MODEL.json --json
python3 -m compactkernel check MODEL.json --certificate RESULT.compact.jsonl --json
python3 -m compactkernel verify MODEL.json RESULT.compact.jsonl \
  --expected-certificate-sha256 LOWERCASE_SHA256 --json
```

終了コードは0が全照会0件、1が少なくとも一つの照会で具体例あり、2が確定不能。`VERIFIED` は証拠と再評価が一致した意味であり、照会結果0件という意味ではない。
