# 有限規範検証カーネル v0.1

2026-09-16。T08の実装契約。対象profileは`finite-norms/1`、証拠形式は
`finite-norms-certificate/1`である。既存の
[`finite-decisions/1`](kernel-v0.1.md)を読み替えず、独立した`normkernel`
packageとCLIで扱う。

この版は、有限状況ごとに有限の行動候補を全列挙し、背景上可能な候補、義務・禁止を
同時に守る候補、明示的許可を行使できる候補を区別する。原文からの正しい形式化、
現実の行為、違反の成立、法的な権限・裁量は判定しない。

## モデル

最上位fieldは次の9個だけを受理する。

```text
profile, origin_kind, title,
inputs, facts, constraints,
actions, action_constraints, norms
```

- `profile`は`finite-norms/1`、`origin_kind`は
  `authored_normative_core`に固定する。
- `inputs`は既存Coreと同じBool、有限Enum、閉区間の整数で有限状況を定義する。
- `facts`は`{"var": name, "value": value}`の列。異なる値を同じ入力へ指定した場合は
  `INPUT_INCONSISTENT`とする。
- `constraints`は入力だけを参照するBoolean式で、検査対象となる状況を限定する。
- `actions`は重複のないBoolean原子名の列。入力名との重複を許さない。空でもよい。
- `action_constraints`は入力と行動を参照でき、当該状況で背景上可能な行動候補を定める。
- `norms`は`id, source, kind, when, content`を持つ。`when`は入力だけ、
  `content`は入力と行動を参照できるBoolean式である。

式は`const`、`input`、`action`と、
`eq/ne/lt/le/gt/ge/and/or/not`を扱う。未知field、未宣言名、型の合わない比較、
行動を参照する`constraints`や`when`は拒否する。
未知だが文字列として整ったdomain kind、operator、norm kindは`UNSUPPORTED`、
文字列でない等の壊れた構造は`MODEL_INVALID`として区別する。

規範kindは次の3つだけである。

| kind | このprofileでの意味 |
|---|---|
| `obligation` | activeなら`content`が真の行動候補だけを遵守候補とする |
| `prohibition` | activeなら`content`が偽の行動候補だけを遵守候補とする |
| `explicit_permission` | 遵守制約へ加えず、遵守候補の中で`content`を実現できるかを別に調べる |

義務と禁止を「決定値」へ変換しない。禁止`F(phi)`の遵守条件は`not phi`である。
したがって`F(A and B)`はAとBの同時実行を禁じるが、
`F(A)`と`F(B)`を同時に置く意味ではない。

## 有限意味論と量化順序

宣言入力のCartesian積に属する状況を`c`、全Boolean行動割当を`tau`とする。

```text
D(c)       = facts(c) and all constraints(c)
T(c,tau)   = all action_constraints(c,tau)
H(c,tau)   = all active obligations' content(c,tau)
             and all not(active prohibitions' content(c,tau))
C(c,tau)   = T(c,tau) and H(c,tau)
```

対象状況`D(c)`の中では、規範は`when(c)`が真のときactiveとなる。`D(c)`でない状況は規範の適用判定へ進めず、証拠上のactive規範IDも空にする。明示的許可は`H`へ入らない。
対象状況ごとに行動候補を選べるため、履行可能性の量化は
「すべての対象状況`c`について、その状況用の`tau`が存在する」である。
全状況に共通する一つの行動列を要求しない。

各状況を次の順で一つに分類する。

| classification | 条件 |
|---|---|
| `excluded` | `not D(c)` |
| `background_trace_impossible` | `D(c)`かつ`T(c,tau)`を満たす`tau`がない |
| `normatively_infeasible` | 背景候補はあるが`C(c,tau)`を満たす`tau`がない |
| `compliance_feasible` | `C(c,tau)`を満たす`tau`がある |

背景候補が0なら、同時に規範の衝突も見えるモデルでも
`background_trace_impossible`を優先する。対象状況が1つもなければ
`BASE_INCONSISTENT`で停止し、問題なしとは報告しない。

## 明示的許可

各明示的許可`p`を個別に調べる。

```text
applicable(p,c) = D(c) and p.when(c)
usable(p,c)     = applicable(p,c)
                  and exists tau: C(c,tau) and p.content(c,tau)
```

statusは次の順で決める。

| status | 条件 |
|---|---|
| `not_applicable` | `not D(c)`又は`not p.when(c)` |
| `background_impossible` | activeだが背景候補がない |
| `base_norms_infeasible` | 背景候補はあるが義務・禁止を守る候補がない |
| `unusable` | 遵守候補はあるが許可内容を満たす候補がない |
| `usable` | 許可内容を満たす遵守候補がある |

同じ状況に複数の許可がある場合、それぞれを別の存在量化で検査する。
全許可を同時に行使する一つの候補を要求しない。`P(A)`と`P(not A)`が別々の候補で
両方usableとなることもある。

証拠はusableな候補の件数と最初のwitnessに加え、遵守しつつ許可内容を行わない
`nonexercise_count`とwitnessも保存する。後者が正なら、その状況では許可内容を
行使しなくても遵守できる。0であっても、許可自身が義務を作ったとは結論しない。
別の義務や背景制約が同じ内容を要求している可能性があるためである。

## 証拠

producerは入力名と行動名を辞書順にし、Boolをfalse、trueの順で全列挙する。
右端の名前が最も速く変わる。対象外状況も`cases`へ保存し、対象状況では全行動候補を
`traces`へ保存する。最上位fieldは次のとおり。

```text
format, profile, semantics_version, model_hash, engine_version,
enumeration, counts, cases, permission_summaries
```

`enumeration`は入力・行動順、宣言状況数、行動割当数、潜在的な状況×行動数、
実際に評価した対象状況×行動数を持つ。`counts`は全状況、対象状況と4分類の件数を持つ。

各caseは入力、対象内か、分類、kind別active規範ID、背景候補数、遵守候補数、
各最初のwitness、全trace、許可別の結果を持つ。各traceは行動割当、
背景制約の真偽、activeな義務・禁止ごとの内容値と遵守値、全hard normの遵守、
`C`の真偽を持つ。これにより、要約だけを信用せず全候補から再集計できる。

checkerはproducerの`engine`をimportせず、入力状況、行動割当、式評価、active規範、
4分類、許可、witness、全集計を別実装で再構成する。証拠のcanonical JSON全体が
再構成結果と一致した場合だけ`status: VERIFIED`を返す。`VERIFIED`は証拠検査の成功であり、
`diagnostics.has_findings`とは別である。
診断では利用不能な許可を`permission×context`の組数と、それを含む一意なcontext数へ分け、
複数の許可が同じ状況で利用不能でも件数の意味を混ぜない。checkerはモデルvalidator、canonical JSON/hash、
上限検査、Python処理系と標準ライブラリをproducerと共有する。カーネルの健全性を
機械証明したものではない。

## CLI

```bash
python3 -m normkernel check MODEL \
  --certificate NEW_CERTIFICATE \
  --json

python3 -m normkernel verify MODEL CERTIFICATE \
  --expected-certificate-sha256 EXTERNAL_CANONICAL_SHA256 \
  --json
```

- exit 0: 完全な証拠を独立再検査でき、注意対象がない。
- exit 1: 独立再検査は成功したが、背景だけの行動不能、規範上の履行不能、
  又はactiveなのにunusableな明示的許可がある。
- exit 2: モデル・証拠・anchorの不正、不一致、対象状況0、未対応、上限、
  I/O失敗により確定できない。

`check`もproducer結果をそのまま保存せず、独立checkerで一致を確認してから公開する。
証拠出力は既存path、モデルpathへの上書きを拒否し、失敗時に部分証拠を残さない。
外部hashは証拠のcanonical JSON SHA-256である。保存fixtureはcanonical JSON bytesなので、
その値がfile SHA-256とも一致する。

## 上限

preflightで次を確認し、超える場合は列挙前に`LIMIT_REACHED`とする。

| 対象 | hard limit |
|---|---:|
| モデルのUTF-8 canonical JSON | 1 MiB |
| 完全な証拠 | 8 MiB |
| 入力Cartesian積 | 10,000状況 |
| 1状況のBoolean行動割当 | 4,096 |
| 宣言状況×行動割当 | 100,000組 |

CLIで上限を下げることはできるが、hard limitより上へ広げられない。
ファイル入力ではraw UTF-8 bytesとcanonical JSON bytesの両方に対応する上限を適用する。
factsやconstraintsで除外される状況も宣言全積と潜在組数の予算に含める。
対象外状況にはtraceを保存しないため、`evaluated_context_trace_pairs`は潜在組数より
小さくなりうる。いずれの上限到達も、途中まで問題がなかったという確定結果にしない。

## 保証しない範囲

この版が確認するのは、手で書いた`authored_normative_core`と固定有限domainにおける
候補存在、履行不能の分類、明示的許可の利用可能性だけである。
T05の原文package・review・scope expectationsとはまだ結ばれていない。
自然文の意味対応、法的妥当性、規範間の優先順位・例外、主体・対象・時点の同一性、
実際の行為・違反・救済、法的な権限・裁量、期限・イベント列、無限領域、
一般SAT/UNSAT、LLM候補生成は対象外である。

実装は[`model.py`](../normkernel/model.py)、[`engine.py`](../normkernel/engine.py)、
[`checker.py`](../normkernel/checker.py)、[`__main__.py`](../normkernel/__main__.py)。
固定例は[`examples/norms/t08-three-way/`](../examples/norms/t08-three-way/)、
回帰は[`test_normative_kernel.py`](../tests/test_normative_kernel.py)、
[`test_normative_cli.py`](../tests/test_normative_cli.py)、
[`test_t08_normative_example.py`](../tests/test_t08_normative_example.py)に置く。
