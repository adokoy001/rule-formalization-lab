# T08 有限規範カーネルの検証記録

日付: 2026-09-16

## 対象と結論

T08では、既存の決定モデル`finite-decisions/1`を変更せず、別package
`normkernel`に時間なしの`finite-norms/1`を実装した。有限状況`c`と
Boolean行動候補`tau`を別々に全列挙し、次を区別する。

- facts又はconstraintsにより対象外となる状況。
- 対象内だがaction constraintsだけで候補が0になる状況。
- 背景候補はあるが、義務と禁止を同時に守る候補がない状況。
- 義務と禁止を守る候補がある状況。
- 明示的許可ごとに、遵守しながら許可内容を行使できる候補と、行使しない候補。

実装契約は[有限規範検証カーネル v0.1](normative-kernel-v0.1.md)、固定した架空例は
[T08 架空の三者規範](../examples/norms/t08-three-way/README.md)にある。

検証した結論は、手で書いた`authored_normative_core`と宣言有限領域についての
候補存在と分類である。架空原文からモデルへの意味対応、実法令、実際の違反、
主体、時系列、期限、権限又は裁量は検証していない。

## 実装した経路

公開CLIは次の二つである。

```bash
python3 -m normkernel check MODEL [--certificate NEW_PATH] [--json]
python3 -m normkernel verify MODEL CERTIFICATE \
  [--expected-certificate-sha256 SHA256] [--json]
```

`check`はproducerが完全証拠を作り、producerの`engine`をimportしないcheckerが
全状況・全行動候補を再計算して一致した後だけ証拠を公開する。
`verify`は保存証拠を同じ独立経路で再検査する。両者の`status: VERIFIED`は
証拠と独立再計算の一致を表し、注意対象0を意味しない。

この実装は既存`rulekernel`を変更しない別package・別CLIにした。これは新しい
規範意味論を既存decisionへ黙って追加しないためであり、T06正式reportが現在の
`rulekernel` source pathのhashを照合する既知制約による不要なstale化も避ける。

実装:

- [model.py](../normkernel/model.py): 厳密JSON、型付きモデル、有限領域、上限の検査。
- [engine.py](../normkernel/engine.py): 状況と行動候補の全列挙、証拠生成。
- [checker.py](../normkernel/checker.py): producer非依存の再評価と完全証拠照合。
- [__main__.py](../normkernel/__main__.py): `check` / `verify`、終了コード、原子的な非上書き保存。

## 固定fixture

[架空原文](../examples/norms/t08-three-way/source.txt)は次の4規範を持つ。

1. `O(A or B)`: A又はBの少なくとも一方を行う義務。
2. `F(A)`: Aの禁止。
3. `strict`の場合の`F(B)`: Bの禁止。
4. `P(C)`: Cの明示的許可。

入力はBoolの`blocked`、`in_scope`、`strict`、行動はBoolのA、B、Cである。
`in_scope`だけをadmitし、`blocked`ならaction constraintにより全行動候補を
背景不可能にする。

保存ファイルとSHA-256:

| 対象 | bytes | SHA-256 |
|---|---:|---|
| [source.txt](../examples/norms/t08-three-way/source.txt) | 256 | `5329107793e80775b1996a2d084451043c217ec55bf8485f77f1eb69cdfc1a82` |
| [model.json](../examples/norms/t08-three-way/model.json) | 1,044 | `0d71e04b1c43038754638a6e52dca63771318902564df8cca278f495486ed839` |
| [certificate.json](../examples/norms/t08-three-way/certificate.json) | 17,796 | `a61cbda1b788a60e11988cda9a8468b14b5bf4e098f701c1435c867dda448b8a` |

modelとcertificateはcanonical JSON bytesであり、file hashとcanonical hashが一致する。
source hashはUTF-8 file bytesを固定する。

## 保存証拠の再検査

実行したコマンド:

```bash
python3 -m normkernel verify \
  examples/norms/t08-three-way/model.json \
  examples/norms/t08-three-way/certificate.json \
  --expected-certificate-sha256 a61cbda1b788a60e11988cda9a8468b14b5bf4e098f701c1435c867dda448b8a \
  --json
```

結果は`status: VERIFIED`、`certificate_hash_anchored: true`、exit 1だった。
exit 1は証拠検査の失敗ではなく、背景不能又は規範上の履行不能という注意対象が
保存結果にあるためである。

| 集計 | 件数 |
|---|---:|
| 全入力状況 | 8 |
| admitted | 4 |
| 1状況あたりの行動割当 | 8 |
| 潜在 context/trace 組 | 64 |
| 実際に評価した context/trace 組 | 32 |
| excluded | 4 |
| background_trace_impossible | 2 |
| normatively_infeasible | 1 |
| compliance_feasible | 1 |

`strict=false, blocked=false, in_scope=true`では、遵守候補は正確に次の2件だった。

- `A=false, B=true, C=false`
- `A=false, B=true, C=true`

`P_C`は前者をnonexercise witness、後者をusable witnessとして各1件持つ。
したがってこのfixtureでは、明示的許可を遵守条件へ入れず、Cを行使してもしなくても
義務・禁止を守れることを証拠から再構成できる。

producer再生成も存在しない一時pathに対して実行した。exit 1 / `VERIFIED`となり、
生成certificateのSHA-256は`a61cbda...48b8a`、保存certificateとbyte-for-byteで一致した。

## 固定した負例

専用回帰は次を確認する。

- `O(A or B)`、`F(A)`、`F(B)`の三者が揃ったときだけ当該状況が履行不能になり、どれを一つ削っても遵守候補が戻る。
- ある状況の遵守候補を別状況へ流用せず、`for every c, exists tau`の順で検査する。
- `F(A and B)`を`F(A)`かつ`F(B)`へ読み替えない。
- 複数の明示的許可は個別の存在量化で調べ、全許可を同時行使する候補を要求しない。
- 背景候補0を規範上の履行不能より先に分類する。
- activeな許可がunusableでも、基礎の義務・禁止を守れる状況自体は`compliance_feasible`にできる。
- 入力矛盾、未知profile・kind・operator、不正型、空background、状況・行動・積・証拠bytesの上限を確定成功にしない。
- producer評価の意図的変異、case・trace・集計・permission witnessの改ざん、モデル差替え、誤った外部hashをcheckerが拒否する。
- 既存又は入力と同じcertificate pathを上書きせず、公開競合又はI/O失敗で部分証拠を残さない。

## テストと静的確認

```bash
python3 -m unittest \
  tests.test_normative_kernel \
  tests.test_normative_cli \
  tests.test_t08_normative_example -v

python3 -m unittest discover -s tests -v
python3 -m compileall -q rulekernel normkernel tests benchmarks
python3 -m benchmarks.t06.report_checker \
  benchmarks/t06/results/2026-09-15.json \
  --expected-report-sha256 6bda457de5e19dbcbd74bb7df50f528b1c4dd6ca1e1040a972af35c7d3af1068
```

T08専用38件は全件合格した。全suiteは301件合格（20.896秒）、
`compileall`はexit 0だった。T06保存report checkerも`VERIFIED`で、
raw SHA-256 `6bda457d...1068`、body SHA-256 `4c9478c8...7fe`を維持した。
T06が結ぶ`rulekernel/__main__.py`のSHA-256も
`d88b254a315b1997011df3cbf517a7d234944427de844ed6f9b6252473578d5a`のままである。

対象はモデル検査、式のtruth table、空入力・空行動、三者履行不能、量化順、
許可の個別利用可能性、上限、独立checker、CLI終了コード、原子的な非上書き公開、
保存fixtureのhashと負例に加え、既存decision、原文package、解釈、段階別診断、
T06 reportの回帰である。

## 上限と残る信頼境界

このprofileのpreflight hard limitは、model 1 MiB、certificate 8 MiB、
入力Cartesian積10,000、1状況の行動割当4,096、宣言状況×行動割当100,000である。
factsやconstraintsにより除外される状況も、宣言全積と潜在組数の予算に含める。
上限へ達した場合は`LIMIT_REACHED` / exit 2で停止し、部分結果を公開しない。

checkerはengineをimportせず全候補を再構成するが、model validator、canonical
JSON/hash、Python処理系、標準ライブラリ、仕様理解は共有する。カーネルの健全性を
機械証明したものではない。

T08は`authored_normative_core`専用で、T05のsource package、candidate、review、
scope expectations、provenance chainへ接続していない。架空の`source.txt`は読みやすい
対応資料であり、checkerが自然文との意味一致を検査する入力ではない。

時間、主体、行動順序、期限、観測終了、実際の履行・違反、救済、規範の優先順位・例外、
権限、裁量、実法令は未実装である。次のT09では、架空の小さな手続に有限イベント列と
時間を別profile又は明示的な意味論拡張として追加する。
