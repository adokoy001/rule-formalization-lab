# T08 架空の三者規範

`finite-norms/1`の最小fixture。有限状況と有限行動候補を分け、義務、禁止、明示的許可を時間なしで全列挙する。

[`source.txt`](source.txt)はこのfixture用の短い架空原文であり、T05のsource packageでも、原文から規範IRへ変換した結果でもない。[`model.json`](model.json)は人が直接書いた`authored_normative_core`である。各`norm.source`は`source.txt`の対応する1行と完全一致する。

## 架空原文とモデル

1. 行為A又は行為Bの少なくとも一方を行う義務 `O_CHOOSE_A_OR_B`
2. 行為Aの禁止 `F_A`
3. `strict`のときだけ行為Bを禁止する `F_B_STRICT`
4. 行為Cの明示的許可 `P_C`

入力`blocked`、`in_scope`、`strict`はいずれもBooleanで、全入力状況は8件。`in_scope`を背景constraintにして4件だけをadmitする。行動候補はA、B、CのBoolean全積8件である。`not blocked`をaction constraintにしたため、`blocked=true`のadmitted状況では規範を見る前に全行動候補が背景不可能になる。

時点や行動列はまだ持たず、一つの行動候補`tau`はA、B、Cをその場で行うかどうかのBoolean割当てである。

## 固定した意味と量化順

各入力状況`c`について、factsとconstraintsを満たすかを先に調べる。admittedな各`c`に対して全行動候補`tau`を列挙し、次を別々に計算する。

- `T(c,tau)`: action constraintsをすべて満たす。
- `H(c,tau)`: activeな義務のcontentがtrueで、activeな禁止のcontentがfalse。
- `C(c,tau) = T(c,tau) and H(c,tau)`: 背景にも義務・禁止にも適合する。

検査する履行可能性は、各admitted状況ごとに適合候補が少なくとも一つ存在するか、すなわち `for every admitted c, exists tau: C(c,tau)` である。全状況で共通する一つの`tau`は要求しない。

明示的許可は`H`へ入れない。`P_C`がusableとは、`C(c,tau)`を満たし、かつCを行う候補が少なくとも一つあるという意味である。Cを行わないcompliant候補も同時に残るため、`P_C`を`O(C)`へ読み替えない。

## 保存結果

[`certificate.json`](certificate.json)は公開CLI `normkernel check`のproducer出力を、別実装のcheckerが全件再計算した後にcanonical JSONで保存したもの。結果には履行不能のfindingsがあるため、`status: VERIFIED`でもCLIの終了コードは1となる。

| 集計 | 件数 |
|---|---:|
| input contexts | 8 |
| admitted contexts | 4 |
| action assignments per admitted context | 8 |
| potential context/trace pairs | 64 |
| evaluated context/trace pairs | 32 |
| excluded | 4 |
| background trace impossible | 2 |
| normatively infeasible | 1 |
| compliance feasible | 1 |

状況分類は次のとおり。

| `in_scope` | `blocked` | `strict` | 分類 | compliant候補 |
|---|---|---|---|---:|
| false | 任意 | 任意 | excluded | 0 |
| true | true | false / true | background_trace_impossible | 0 |
| true | false | true | normatively_infeasible | 0 |
| true | false | false | compliance_feasible | 2 |

最後の2候補は正確に次の二つである。

- `A=false, B=true, C=false`
- `A=false, B=true, C=true`

後者が`P_C`のusable witness、前者がnonexercise witnessである。`strict=true, blocked=false`では`O(A or B)`、`F(A)`、`F(B)`の三者が初めて履行不能を作る。三者のどれを一つ削っても、その状況にはcompliant候補が戻る。

## 外部hash

modelとcertificateはcanonical bytesで保存しており、次のSHA-256はファイルhashと意味上のcanonical hashの両方に一致する。source hashは架空原文のUTF-8ファイルbytesを固定する。

| 対象 | SHA-256 |
|---|---|
| source.txt | `5329107793e80775b1996a2d084451043c217ec55bf8485f77f1eb69cdfc1a82` |
| model.json | `0d71e04b1c43038754638a6e52dca63771318902564df8cca278f495486ed839` |
| certificate.json | `a61cbda1b788a60e11988cda9a8468b14b5bf4e098f701c1435c867dda448b8a` |

## 再検査

repo rootで保存物のbytesを外部値と照合する。

```bash
sha256sum \
  examples/norms/t08-three-way/source.txt \
  examples/norms/t08-three-way/model.json \
  examples/norms/t08-three-way/certificate.json
```

保存certificateを外部certificate hash付きで独立再検査する。

```bash
python3 -m normkernel verify \
  examples/norms/t08-three-way/model.json \
  examples/norms/t08-three-way/certificate.json \
  --expected-certificate-sha256 a61cbda1b788a60e11988cda9a8468b14b5bf4e098f701c1435c867dda448b8a \
  --json
```

producerから同じ証拠を再生成する場合は、存在しない出力パスを指定する。次の例は`/tmp/t08-three-way-replay.certificate.json`が存在しない場合に使える。出力SHA-256は上記certificate hashと一致する。

```bash
python3 -m normkernel check \
  examples/norms/t08-three-way/model.json \
  --certificate /tmp/t08-three-way-replay.certificate.json \
  --json
```

両CLIは、独立再計算が一致したことを`VERIFIED`で示す。一方で診断はbackground impossible 2件とnormatively infeasible 1件を残すため、終了コード1を返す。

## このsliceの限界

検証済みなのは、この架空の3入力、3行動、4規範からなる有限モデルと保存証拠の対応だけである。自然言語からモデルへの変換、実法令、主体、行動順序、時間、期限、裁量、権限、実際の違反、制裁、救済、義務間の優先関係は扱わない。permissionは基礎の義務・禁止と両立する行動候補の存在だけを調べ、禁止の解除や例外としては働かない。
