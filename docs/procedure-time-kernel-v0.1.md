# 有限手続・時間カーネル v0.1

2026-09-16。T09の実装契約である。対象profileは`finite-procedure-time/1`、
証拠形式は`finite-procedure-time-certificate/1`とする。T08の
`finite-norms/1`の時間なし意味論を変更せず、独立した`procedurekernel` packageと
CLIで扱う。

この版は、手書きした架空の手続モデルについて、固定された観測prefixと少数の将来event
候補を全列挙する。手続順序、起算event、包含期限、部分的禁止、観測未完了を区別する。
有限候補で得た結果は実時間全体、自然文の正しい形式化、又は法的判断を意味しない。

## モデルと座標

最上位fieldは次の9個だけを受理する。

```text
profile, origin_kind, title, time_unit, observation_mode,
slots, background_constraints, norms, contexts
```

- `profile`は`finite-procedure-time/1`、`origin_kind`は
  `authored_procedure_core`、`observation_mode`は`closed_prefix`に固定する。
- `time_unit`はモデル全体で一つの識別子とする。`tick`から日、時間、秒への変換はしない。
- 座標は符号付き64 bit整数`tick`と、0以上1,000,000以下の整数`phase`の組
  `(tick, phase)`で、辞書式順序を使う。加算はtickだけに行い、桁あふれを拒否する。
- 同じ座標のeventは同時である。証拠のevent列はslot ID順に保存するが、この保存順から
  意味上の先後を作らない。同じtickでもphaseが異なれば先後がある。

`slots`は最大8個で、`id, actor, kind`を持つ。一つのslotは一つのtrace中で0回又は1回だけ
発生する。同じkindを複数slotへ割り当てる反復・多重度は`UNSUPPORTED`とする。

## 外生的な観測終了と有限候補

各contextは`id, observation_end, observed, future`を持つ。
`observation_end`は候補traceが選べない外生的な**排他的観測終了座標**である。

```text
observed event coordinate < observation_end
future candidate coordinate >= observation_end
```

したがって、包含期限`due`に対して未記録のeventは、`observation_end == due`ではまだ
`pending`であり、`observation_end > due`になって初めて`violated_missing`となる。
期限ちょうどのeventは、観測終了が期限より後のprefixで観測済みにできる。排他期限なら、
未記録は`observation_end >= due`で確定する。

`observed`はslotと既知座標又は`null`を持つ。`null`はeventの発生は観測されたが時刻が
未確定であることを表し、不発生に変換しない。`future`は未観測slotごとに有限座標列を持つ。
各future slotは列挙時に`absent`又はいずれか一座標を選ぶ。候補trace数は列挙前に
次式で求める。

```text
product over future slots (1 + declared coordinate count)
```

宣言slotについて観測終了より前に記録がなければ不発生とするclosed-world prefixだけを
扱う。過去の未記録を不明とするopen-world観測は`UNSUPPORTED`である。future候補にない
実時間上の座標を網羅したとは扱わない。

completion候補の`absent`は、その有限traceではeventが発生しない選択である。したがって、
起算点が確定したdeadlineのcompletionで全targetがabsentなら`violated_missing`となる。
一方、固定されたobserved prefix上の未記録は排他的cutの規則に従って`pending`になり得る。
この差により、有限候補上は`normatively_infeasible`でも、現時点の観測評価は`pending`という
結果を明示できる。

## 手続順序

`background_constraints`の`precedence`は`before, after, relation`を持つ。

- `strict_before`: 両eventがある場合に`before < after`を要求する。
- `not_after`: 両eventがある場合に`before <= after`を要求し、同時を許す。
- `after`が発生したのに`before`がなければ、手続の前提遷移を欠くため違反とする。
- `after`がまだなければ、先行eventの有無だけで背景不能とはしない。
- 比較に必要な時刻が`null`なら`unresolved_time`とする。

この背景評価は、規範に違反する候補と、そもそも手続列として不可能な候補を分ける。

## 規範

全規範は同時に適用する。優先順位、例外、overrideを表すfieldはなく、追加されても拒否する。

### deadline

`anchor, targets, min_offset, max_offset, inclusive`を持つ。`targets`は1〜8個のslotで、
いずれか一つが期間内にあれば義務内容を満たすany-ofである。

```text
start = anchor + min_offset
due   = anchor + max_offset

inclusive=true:  start <= target <= due
inclusive=false: start <= target <  due
```

期間内の候補が複数あれば、座標、slot IDの順で最初のものを証拠の`selected_target`にする。
これはwitnessのcanonical化であり、法的な選択優先順位ではない。

### prohibition_window

`anchor, targets, start_offset, end_offset, inclusive_start, inclusive_end`を持つ。
この版の`targets`はちょうど1 slotに限定する。そのtargetが禁止窓内にあれば違反となる。
窓外のeventは、禁止の終了によって許される
候補であり、規範overrideや規範削除とは呼ばない。

## 三つの独立した結果軸

証拠の正しさ、将来completionの存在、観測済みprefixの現在評価を混ぜない。

1. checkerが証拠全体を再構成できたかを`VERIFIED`又は検査失敗statusで返す。
2. contextごとの`classification`は有限候補集合のcompletion feasibilityを返す。
3. contextごとの`observed_outcome`と規範別`status`は固定prefixだけを評価する。

completion feasibilityは次の順で決める。

| classification | 条件 |
|---|---|
| `background_trace_impossible` | 背景違反でない候補が0 |
| `compliance_feasible` | 背景と全規範を確定的に満たす候補が1以上 |
| `normatively_infeasible` | 背景候補はあるが、すべてに確定的な規範違反がある |
| `completion_unresolved` | 背景候補はあるが、満足候補はなく未確定statusが残る |

主な規範別statusは`satisfied`、`pending`、`violated_missing`、
`violated_too_early`、`violated_late`、`violated_prohibited_window`、
`anchor_missing`、`pending_anchor`、`anchor_time_unresolved`、
`target_time_unresolved`である。contextの`observed_outcome`は`fulfilled`、`pending`、
`violated`、`unresolved_anchor`、`unresolved_time`、`background_violated`を区別する。
一つの規範だけが違反したcontextを、別contextの成功で隠さず集計する。

## 証拠と独立checker

producerはcontext ID、future slot ID、各slotの`absent`、座標順をcanonicalな順序で全列挙する。
証拠にはmodel hash、列挙順・件数、全traceのevent、背景評価、規範別評価、分類、
最初の背景witnessと遵守witness、全集計を保存する。

checkerはproducerの`engine`をimportせず、座標比較、候補列挙、背景制約、期限と禁止窓、
観測判定、any-of target、分類、witness、集計を別実装で再構成する。branchの欠落・重複・
順序変更、偽集計、偽witness、model/hash変更を完全一致で拒否する。共通利用するのは厳格JSON、
validator、canonical JSON/hash、検査付き座標加算、上限定数であり、機械証明ではない。

## 上限

| 対象 | hard limit |
|---|---:|
| modelのraw/canonical UTF-8 | 1 MiB |
| 完全証拠 | 8 MiB |
| event slot | 8 |
| context | 10,000 |
| 1 contextの候補trace | 4,096 |
| context×trace | 100,000 |

候補数と算術桁あふれは列挙前に検査し、超過を`LIMIT_REACHED`とする。途中結果は公開しない。

## CLI

```bash
python3 -m procedurekernel generate MODEL --certificate NEW_CERTIFICATE --json
python3 -m procedurekernel verify MODEL CERTIFICATE \
  --expected-certificate-sha256 EXTERNAL_SHA256 --json
```

- exit 0: 証拠を独立再検査でき、診断対象がない。
- exit 1: 証拠は`VERIFIED`だが、未完了・未確定・背景不能・規範不能・違反がある。
- exit 2: model、証拠、anchor、上限又はI/Oの問題で検査結果が未確定。

`generate`もchecker合格後にだけ証拠を公開する。既存pathとmodel pathへの上書きを拒否し、
一時fileをfsyncしてhard linkで新規公開する。競合やI/O失敗時に部分証拠を残さない。

## 対象外

暦日・休日・期間計算、単位変換、同kind eventの反復、open-world過去観測、無限又は連続時間、
「直ちに」「相当」等の評価語、権限・裁量・制裁・救済、優先関係・override、原文との意味対応、
実法令の正しい解釈は未対応である。T10で同じprofileを用いる場合も、法令source/review/scopeの
来歴と限定解釈を別に固定し、この架空例を法解釈として流用しない。
